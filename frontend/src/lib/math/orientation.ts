import { Quaternion, Vector3 } from 'three';
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
 * Convert equatorial J2000 RA/Dec to ecliptic J2000 longitude/latitude.
 * Rotates around the X axis by the obliquity of the ecliptic.
 */
function equatorialToEcliptic(raDeg: number, decDeg: number): [number, number] {
	const ra = raDeg * DEG2RAD;
	const dec = decDeg * DEG2RAD;

	// Equatorial unit vector
	const cosD = Math.cos(dec);
	const xEq = cosD * Math.cos(ra);
	const yEq = cosD * Math.sin(ra);
	const zEq = Math.sin(dec);

	// Rotate around X by obliquity (equatorial -> ecliptic)
	const xEcl = xEq;
	const yEcl = yEq * COS_OBL + zEq * SIN_OBL;
	const zEcl = -yEq * SIN_OBL + zEq * COS_OBL;

	const lat = Math.asin(zEcl);
	const lon = Math.atan2(yEcl, xEcl);

	return [lon, lat]; // radians
}

/**
 * Apply body orientation (axial tilt + spin) to a Three.js mesh.
 *
 * The mesh's local Y-axis is treated as its default pole direction.
 * This function computes a quaternion that:
 * 1. Tilts the pole from the ecliptic north to the body's actual pole direction
 * 2. Applies spin rotation around the pole axis
 *
 * Coordinate system: ecliptic X→X, ecliptic north (Z)→Y, ecliptic Y→Z
 */
export function applyOrientation(mesh: Mesh, orientation: Orientation, currentJd: number): void {
	const { pole_ra, pole_dec, w0, w_rate } = orientation;

	// Convert pole direction from equatorial to ecliptic
	const [eclLon, eclLat] = equatorialToEcliptic(pole_ra, pole_dec);

	// Pole direction as unit vector in ecliptic coordinates
	const cosLat = Math.cos(eclLat);
	const poleEclX = cosLat * Math.cos(eclLon);
	const poleEclY = cosLat * Math.sin(eclLon);
	const poleEclZ = Math.sin(eclLat);

	// Map ecliptic (X, Y, Z) to Three.js (X, Z, Y) — same mapping as orbitalToThreeJS
	// ecliptic X -> Three.js X, ecliptic Z (north pole) -> Three.js Y, ecliptic Y -> Three.js Z
	const poleThreeJS = new Vector3(poleEclX, poleEclZ, poleEclY);
	poleThreeJS.normalize();

	// Compute quaternion that rotates default Y-axis (0,1,0) to pole direction
	const defaultPole = new Vector3(0, 1, 0);
	const tiltQuat = new Quaternion().setFromUnitVectors(defaultPole, poleThreeJS);

	// Compute spin angle: W = W0 + W_rate * (JD - J2000)
	const dt = currentJd - J2000_JD;
	const spinAngle = (w0 + w_rate * dt) * DEG2RAD;

	// Spin around the pole axis (local Y after tilt)
	const spinQuat = new Quaternion().setFromAxisAngle(poleThreeJS, spinAngle);

	// Apply: first tilt, then spin
	mesh.quaternion.copy(spinQuat.multiply(tiltQuat));
}
