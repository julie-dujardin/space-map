import { Matrix4, Quaternion, Vector3 } from 'three';
import type { Mesh } from 'three';

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
 * and arrives via /data/v1/nut_prec_angles.json, indexed by owner naif_id
 * (`naif_id // 100` for moons/planets, `naif_id` itself when < 100).
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
 * Apply body orientation (axial tilt + spin) to a Three.js mesh.
 *
 * The mesh is oriented so that its local +Y axis is the body's north pole and
 * its local +X axis is the IAU ascending node Q (intersection of the body's
 * equator with the ICRF equator where the body equator crosses south→north).
 * The prime meridian (local +X after the spin) is at angle W from Q along the
 * equator, following the IAU convention. This matches the longitude system used
 * by USGS / Blue Marble equirectangular maps (u=0 at longitude ±180°, longitude
 * increasing east through u=0.5 at longitude 0°).
 */
export function applyOrientation(
	mesh: Mesh,
	orientation: Orientation,
	currentJd: number,
	nutPrec?: NutPrec
): void {
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
	mesh.quaternion.copy(spinQuat.multiply(tiltQuat));
}
