import { Matrix4, Quaternion, Vector3 } from 'three';
import type { Object3D } from 'three';
import { equatorialToScene } from '$lib/math/units';
import { J2000_JD, utcToTdb } from '$lib/time/jd';

const DEG2RAD = Math.PI / 180;

/** Julian days per Julian century. */
const DAYS_PER_CENTURY = 36525;

/**
 * SPICE PCK rotation polynomial for a body, equatorial J2000 frame.
 *   α(T) = pole_ra_0 + pole_ra_1·T   (T = Julian centuries since J2000)
 *   δ(T) = pole_dec_0 + pole_dec_1·T
 *   W(d) = w0 + w1·d + w2·d²         (d = days since J2000)
 * Plus optional nutation/precession sums delivered separately as `NutPrec`.
 */
export interface Orientation {
	pole_ra_0: number;
	pole_ra_1: number;
	pole_dec_0: number;
	pole_dec_1: number;
	w0: number;
	w1: number;
	w2: number;
}

/**
 * IAU nutation/precession sums:
 *   α += Σ ra[i]  · sin(θ_i(T))
 *   δ += Σ dec[i] · cos(θ_i(T))
 *   W += Σ pm[i]  · sin(θ_i(T))
 * with θ_i(T) = Σ_j angles[k·i + j] · T^j, k = phaseDegree + 1 (degrees, per century^j).
 *
 * `angles` and `phaseDegree` are shared per system (SPICE convention), from
 * global.json, keyed by owner naif_id (`naif_id // 100` for moons).
 */
export interface NutPrec {
	ra: number[];
	dec: number[];
	pm: number[];
	angles: number[];
	phaseDegree: number;
}

/** The sums of {@link NutPrec} that belong to one body, as the export ships them. */
export type NutPrecSums = Pick<NutPrec, 'ra' | 'dec' | 'pm'>;

/** The IAU angles at an app (UTC) Julian date, in degrees: the pole's right
 *  ascension and declination on equatorial J2000 axes, and the prime
 *  meridian's W. The IAU model counts TDB days. */
export function iauAngles(
	orientation: Orientation,
	currentJd: number,
	nutPrec?: NutPrec
): { ra: number; dec: number; w: number } {
	const dt = utcToTdb(currentJd) - J2000_JD;
	const T = dt / DAYS_PER_CENTURY;

	let raDeg = orientation.pole_ra_0 + orientation.pole_ra_1 * T;
	let decDeg = orientation.pole_dec_0 + orientation.pole_dec_1 * T;
	let wDeg = orientation.w0 + orientation.w1 * dt + orientation.w2 * dt * dt;

	if (nutPrec) {
		const { ra, dec, pm, angles } = nutPrec;
		const k = nutPrec.phaseDegree + 1;
		const n = Math.min(Math.floor(angles.length / k), Math.max(ra.length, dec.length, pm.length));
		for (let i = 0; i < n; i++) {
			let thetaDeg = 0;
			for (let j = k - 1; j >= 0; j--) thetaDeg = thetaDeg * T + angles[k * i + j];
			const theta = thetaDeg * DEG2RAD;
			const s = Math.sin(theta);
			if (i < ra.length) raDeg += ra[i] * s;
			if (i < dec.length) decDeg += dec[i] * Math.cos(theta);
			if (i < pm.length) wDeg += pm[i] * s;
		}
	}
	return { ra: raDeg, dec: decDeg, w: wDeg };
}

/**
 * Body-fixed quaternion (axial tilt + spin) in the scene frame, at an app (UTC)
 * Julian date. Local +Y is the north pole. Local +X is the prime meridian: the
 * IAU ascending node Q turned by W along the equator. This matches the
 * USGS/Blue Marble equirectangular textures.
 */
export function bodyQuaternion(
	orientation: Orientation,
	currentJd: number,
	nutPrec?: NutPrec
): Quaternion {
	const { ra: raDeg, dec: decDeg, w: wDeg } = iauAngles(orientation, currentJd, nutPrec);
	const ra = raDeg * DEG2RAD;
	const dec = decDeg * DEG2RAD;
	const cosDec = Math.cos(dec);

	const pole = equatorialToScene(
		cosDec * Math.cos(ra),
		cosDec * Math.sin(ra),
		Math.sin(dec),
		new Vector3()
	).normalize();

	// Ascending node in equatorial J2000: Q = (K × P) / |K × P| = (−sin α, cos α, 0).
	const node = equatorialToScene(-Math.sin(ra), Math.cos(ra), 0, new Vector3()).normalize();

	// Right-handed basis: local +X → Q, local +Y → P, local +Z → Q × P.
	const third = new Vector3().crossVectors(node, pole).normalize();
	const tiltQuat = new Quaternion().setFromRotationMatrix(
		new Matrix4().makeBasis(node, pole, third)
	);

	const spinQuat = new Quaternion().setFromAxisAngle(pole, wDeg * DEG2RAD);
	return spinQuat.multiply(tiltQuat);
}

/** Apply body orientation (axial tilt + spin) to a Three.js object (sphere mesh
 *  or shape-model root — only the quaternion is touched). */
export function applyOrientation(
	obj: Object3D,
	orientation: Orientation,
	currentJd: number,
	nutPrec?: NutPrec
): void {
	obj.quaternion.copy(bodyQuaternion(orientation, currentJd, nutPrec));
}

const LOCAL_NORTH = new Vector3(0, 1, 0);
const zenithDir = new Vector3();

/**
 * Fallback attitude for sats/probes lacking IAU data: aim local +Y (north)
 * away from the parent, so the south pole faces it (nadir). Recomputed per
 * frame to track the moving parent; no-op when body and parent coincide.
 */
export function applySouthTowardParent(
	obj: Object3D,
	bodyPos: readonly [number, number, number],
	parentPos: readonly [number, number, number]
): void {
	zenithDir.set(bodyPos[0] - parentPos[0], bodyPos[1] - parentPos[1], bodyPos[2] - parentPos[2]);
	if (zenithDir.lengthSq() < 1e-20) return;
	zenithDir.normalize();
	obj.quaternion.setFromUnitVectors(LOCAL_NORTH, zenithDir);
}

/** Aim local +Y along `dir` (unit, scene frame), roll free — landed probes
 *  stand on their terrain facet's normal rather than the radial zenith. */
export function applyUpVector(obj: Object3D, dir: Vector3): void {
	obj.quaternion.setFromUnitVectors(LOCAL_NORTH, dir);
}

/** A landing's stated heading: from `jd` on, the craft's front faces `deg`,
 *  clockwise from north. */
export interface LandedHeading {
	jd: number;
	deg: number;
}

/** The heading of the latest landing at or before `jd`. */
export function landedHeadingAt(
	headings: readonly LandedHeading[] | undefined,
	jd: number
): number | undefined {
	let deg: number | undefined;
	for (const h of headings ?? []) if (h.jd <= jd) deg = h.deg;
	return deg;
}

const LOCAL_FRONT = new Vector3(0, 0, 1);
const _up = new Vector3();
const _front = new Vector3();
const _north = new Vector3();
const _east = new Vector3();
const _target = new Vector3();
const _cross = new Vector3();
const _turn = new Quaternion();

/**
 * Turn an object that already stands on its up axis (local +Y) about that
 * axis, so its local +Z faces `headingDeg` clockwise from `north`. +Z is
 * glTF's front, which a lander model is baked to face. North is the radial
 * frame's; on a tilted seat it is projected onto the seat's plane.
 */
export function turnToHeading(obj: Object3D, north: Vector3, headingDeg: number): void {
	_up.copy(LOCAL_NORTH).applyQuaternion(obj.quaternion);
	_north.copy(north).addScaledVector(_up, -north.dot(_up)).normalize();
	_east.crossVectors(_north, _up);
	const h = headingDeg * DEG2RAD;
	_target.copy(_north).multiplyScalar(Math.cos(h)).addScaledVector(_east, Math.sin(h));
	_front.copy(LOCAL_FRONT).applyQuaternion(obj.quaternion);
	_front.addScaledVector(_up, -_front.dot(_up)).normalize();
	const angle = Math.atan2(_cross.crossVectors(_front, _target).dot(_up), _front.dot(_target));
	obj.quaternion.premultiply(_turn.setFromAxisAngle(_up, angle));
}

export type PointingAxis = '+x' | '-x' | '+y' | '-y' | '+z' | '-z';
export type PointingTarget = 'parent' | 'sun' | 'velocity';

/** Aim one body axis at one world target. */
export interface PointingConstraint {
	axis: PointingAxis;
	target: PointingTarget;
}

/**
 * Per-spacecraft pointing spec (`pointing`, hand-edited in
 * spacecraft-orientation.yaml). `primary` axis aims exactly at its target;
 * optional `secondary` rolls as close as possible to its own. Primary-only
 * leaves roll free.
 */
export interface PointingSpec {
	primary: PointingConstraint;
	secondary?: PointingConstraint;
}

/** World-space inputs a pointing spec resolves its targets against. */
export interface PointingContext {
	bodyPos: readonly [number, number, number];
	parentPos: readonly [number, number, number];
	sunPos?: readonly [number, number, number];
	/** World-space velocity (any magnitude); used by the `velocity` target. */
	velocity?: readonly [number, number, number];
}

const AXIS_VECTORS: Record<PointingAxis, Vector3> = {
	'+x': new Vector3(1, 0, 0),
	'-x': new Vector3(-1, 0, 0),
	'+y': new Vector3(0, 1, 0),
	'-y': new Vector3(0, -1, 0),
	'+z': new Vector3(0, 0, 1),
	'-z': new Vector3(0, 0, -1)
};

/**
 * Model→body rotation from a `frame_map` (1–2 axis pairs). One pair gives a
 * minimal roll-free rotation; two perpendicular pairs pin the full frame.
 * Returns null on a malformed map so a bad manifest degrades to unrotated.
 */
export function frameMapQuaternion(map: Record<string, string>): Quaternion | null {
	const pairs: [Vector3, Vector3][] = [];
	for (const [modelAxis, bodyAxis] of Object.entries(map)) {
		const m = AXIS_VECTORS[modelAxis as PointingAxis];
		const b = AXIS_VECTORS[bodyAxis as PointingAxis];
		if (!m || !b) {
			console.warn(`frame_map: invalid axis pair ${modelAxis}→${bodyAxis}; ignoring map`);
			return null;
		}
		pairs.push([m, b]);
	}
	if (pairs.length < 1 || pairs.length > 2) {
		console.warn(`frame_map: expected 1–2 axis pairs, got ${pairs.length}; ignoring map`);
		return null;
	}
	if (pairs.length === 1) return new Quaternion().setFromUnitVectors(pairs[0][0], pairs[0][1]);
	const [[m1, b1], [m2, b2]] = pairs;
	if (m1.dot(m2) !== 0 || b1.dot(b2) !== 0) {
		console.warn('frame_map: the two pairs must use perpendicular axes; ignoring map');
		return null;
	}
	const m3 = new Vector3().crossVectors(m1, m2);
	const b3 = new Vector3().crossVectors(b1, b2);
	// R = bodyBasis · modelBasisᵀ maps each model axis onto its body axis.
	const body = new Matrix4().makeBasis(b1, b2, b3);
	const model = new Matrix4().makeBasis(m1, m2, m3).transpose();
	return new Quaternion().setFromRotationMatrix(body.multiply(model));
}

const _pWorld = new Vector3();
const _sWorld = new Vector3();
const _e1b = new Vector3();
const _e2b = new Vector3();
const _e3b = new Vector3();
const _e1w = new Vector3();
const _e2w = new Vector3();
const _e3w = new Vector3();
const _mWorld = new Matrix4();
const _mBodyInv = new Matrix4();

/** Resolve a target to a unit world direction in `out`; false if unavailable. */
function resolveTarget(target: PointingTarget, ctx: PointingContext, out: Vector3): boolean {
	if (target === 'parent') {
		out.set(
			ctx.parentPos[0] - ctx.bodyPos[0],
			ctx.parentPos[1] - ctx.bodyPos[1],
			ctx.parentPos[2] - ctx.bodyPos[2]
		);
	} else if (target === 'sun') {
		if (!ctx.sunPos) return false;
		out.set(
			ctx.sunPos[0] - ctx.bodyPos[0],
			ctx.sunPos[1] - ctx.bodyPos[1],
			ctx.sunPos[2] - ctx.bodyPos[2]
		);
	} else {
		if (!ctx.velocity) return false;
		out.set(ctx.velocity[0], ctx.velocity[1], ctx.velocity[2]);
	}
	if (out.lengthSq() < 1e-20) return false;
	out.normalize();
	return true;
}

/**
 * Two-vector attitude: primary axis aims exactly at its target, secondary
 * rolls as close as possible to its own. Falls back to primary-only (roll
 * free) when secondary is unavailable or parallel to primary.
 */
export function applyPointing(obj: Object3D, spec: PointingSpec, ctx: PointingContext): void {
	if (!resolveTarget(spec.primary.target, ctx, _pWorld)) return;
	const primaryAxis = AXIS_VECTORS[spec.primary.axis];

	const sec = spec.secondary;
	if (!sec || !resolveTarget(sec.target, ctx, _sWorld)) {
		obj.quaternion.setFromUnitVectors(primaryAxis, _pWorld);
		return;
	}

	// Build matching orthonormal frames in body & world from (primary, secondary)
	// via the TRIAD recipe; R = worldFrame · bodyFrameᵀ maps body axes → world.
	_e3b.crossVectors(primaryAxis, AXIS_VECTORS[sec.axis]);
	_e3w.crossVectors(_pWorld, _sWorld);
	if (_e3b.lengthSq() < 1e-20 || _e3w.lengthSq() < 1e-20) {
		obj.quaternion.setFromUnitVectors(primaryAxis, _pWorld);
		return;
	}
	_e3b.normalize();
	_e3w.normalize();
	_e1b.copy(primaryAxis);
	_e1w.copy(_pWorld);
	_e2b.crossVectors(_e3b, _e1b);
	_e2w.crossVectors(_e3w, _e1w);
	_mWorld.makeBasis(_e1w, _e2w, _e3w);
	_mBodyInv.makeBasis(_e1b, _e2b, _e3b).transpose();
	_mWorld.multiply(_mBodyInv);
	obj.quaternion.setFromRotationMatrix(_mWorld);
}
