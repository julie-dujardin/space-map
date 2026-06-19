import { Matrix4, Quaternion, Vector3 } from 'three';
import type { Mesh, Object3D } from 'three';

const DEG2RAD = Math.PI / 180;

/** Obliquity of the ecliptic at J2000 epoch (degrees). */
const OBLIQUITY_DEG = 23.4392911;
const OBLIQUITY_RAD = OBLIQUITY_DEG * DEG2RAD;
const COS_OBL = Math.cos(OBLIQUITY_RAD);
const SIN_OBL = Math.sin(OBLIQUITY_RAD);

/** J2000 epoch as Julian Date. */
const J2000_JD = 2451545.0;
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
 * with θ_i(T) = angles[2i] + angles[2i+1]·T (degrees, deg/century).
 *
 * `angles` is shared across all bodies in a planetary system (SPICE convention)
 * and arrives via /data/v1/systems/global.json (in the `nut_prec_angles` field),
 * indexed by owner naif_id (`naif_id // 100` for moons/planets, `naif_id`
 * itself when < 100).
 */
export interface NutPrec {
	ra: number[];
	dec: number[];
	pm: number[];
	angles: number[];
}

/**
 * Rotate an equatorial J2000 unit vector into the three.js scene frame
 * (ecliptic X→scene X, ecliptic north Z→scene Y, ecliptic Y→scene −Z).
 * The Y→−Z flip keeps the mapping a proper rotation (det +1) so chiral
 * quantities like spin axes survive intact.
 */
function equatorialToThreeJS(xEq: number, yEq: number, zEq: number): Vector3 {
	const xEcl = xEq;
	const yEcl = yEq * COS_OBL + zEq * SIN_OBL;
	const zEcl = -yEq * SIN_OBL + zEq * COS_OBL;
	return new Vector3(xEcl, zEcl, -yEcl);
}

/**
 * Build the body-fixed quaternion (axial tilt + spin) for a body at the given
 * Julian date, in Three.js scene coordinates.
 *
 * The result orients the body so that its local +Y axis is the body's north
 * pole and its local +X axis is the IAU ascending node Q (intersection of the
 * body's equator with the ICRF equator where the body equator crosses
 * south→north). The prime meridian (local +X after the spin) is at angle W
 * from Q along the equator, following the IAU convention. This matches the
 * longitude system used by USGS / Blue Marble equirectangular maps (u=0 at
 * longitude ±180°, longitude increasing east through u=0.5 at longitude 0°).
 */
export function bodyQuaternion(
	orientation: Orientation,
	currentJd: number,
	nutPrec?: NutPrec
): Quaternion {
	const dt = currentJd - J2000_JD;
	const T = dt / DAYS_PER_CENTURY;

	let raDeg = orientation.pole_ra_0 + orientation.pole_ra_1 * T;
	let decDeg = orientation.pole_dec_0 + orientation.pole_dec_1 * T;
	let wDeg = orientation.w0 + orientation.w1 * dt + orientation.w2 * dt * dt;

	if (nutPrec) {
		const { ra, dec, pm, angles } = nutPrec;
		const n = Math.min(angles.length >> 1, Math.max(ra.length, dec.length, pm.length));
		for (let i = 0; i < n; i++) {
			const theta = (angles[2 * i] + angles[2 * i + 1] * T) * DEG2RAD;
			const s = Math.sin(theta);
			if (i < ra.length) raDeg += ra[i] * s;
			if (i < dec.length) decDeg += dec[i] * Math.cos(theta);
			if (i < pm.length) wDeg += pm[i] * s;
		}
	}

	const ra = raDeg * DEG2RAD;
	const dec = decDeg * DEG2RAD;
	const cosDec = Math.cos(dec);

	const pole = equatorialToThreeJS(
		cosDec * Math.cos(ra),
		cosDec * Math.sin(ra),
		Math.sin(dec)
	).normalize();

	// Ascending node in equatorial J2000: Q = (K × P) / |K × P| = (−sin α, cos α, 0).
	const node = equatorialToThreeJS(-Math.sin(ra), Math.cos(ra), 0).normalize();

	// Right-handed basis: local +X → Q, local +Y → P, local +Z → Q × P.
	const third = new Vector3().crossVectors(node, pole).normalize();
	const tiltQuat = new Quaternion().setFromRotationMatrix(
		new Matrix4().makeBasis(node, pole, third)
	);

	const spinQuat = new Quaternion().setFromAxisAngle(pole, wDeg * DEG2RAD);
	return spinQuat.multiply(tiltQuat);
}

/** Apply body orientation (axial tilt + spin) to a Three.js mesh. */
export function applyOrientation(
	mesh: Mesh,
	orientation: Orientation,
	currentJd: number,
	nutPrec?: NutPrec
): void {
	mesh.quaternion.copy(bodyQuaternion(orientation, currentJd, nutPrec));
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

export type PointingAxis = '+x' | '-x' | '+y' | '-y' | '+z' | '-z';
export type PointingTarget = 'parent' | 'sun' | 'velocity';

/** Aim one body axis at one world target. */
export interface PointingConstraint {
	axis: PointingAxis;
	target: PointingTarget;
}

/**
 * Per-spacecraft pointing spec (export `pointing`, hand-edited in
 * spacecraft-orientation.yaml). The `primary` body axis is aimed exactly at its
 * target direction; the optional `secondary` axis rolls the model to point as
 * close as possible at its target. Primary-only leaves roll free.
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
 * Two-vector attitude: aim `spec.primary.axis` exactly at its target, then roll
 * `spec.secondary.axis` as close as possible at its target. Degenerates to a
 * single-vector aim (roll free) when there's no secondary, the secondary target
 * is unavailable this frame, or the two directions are parallel. No-op when the
 * primary target can't be resolved.
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
