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

export interface Orientation {
	pole_ra: number; // degrees, equatorial J2000
	pole_dec: number; // degrees, equatorial J2000
	w0: number; // degrees, prime meridian at J2000
	w_rate: number; // degrees/day
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
export function applyOrientation(mesh: Mesh, orientation: Orientation, currentJd: number): void {
	const { pole_ra, pole_dec, w0, w_rate } = orientation;

	const ra = pole_ra * DEG2RAD;
	const dec = pole_dec * DEG2RAD;
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

	const dt = currentJd - J2000_JD;
	const spinAngle = (w0 + w_rate * dt) * DEG2RAD;
	const spinQuat = new Quaternion().setFromAxisAngle(pole, spinAngle);

	mesh.quaternion.copy(spinQuat.multiply(tiltQuat));
}
