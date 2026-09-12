/** 1 AU = this many Three.js units */
export const AU_SCALE = 10;
/** 1 AU in km */
export const AU_KM = 149_597_870.7;
/** Speed of light in km/s */
export const SPEED_OF_LIGHT_KM_S = 299_792.458;
/** Mean obliquity of the ecliptic at J2000 (IAU 2006), in degrees. */
export const EARTH_OBLIQUITY_DEG = 23.4392911;
/**
 * Multiply a GM value in km^3/s^2 by this to get AU^3/day^2 — the canonical
 * units for Kepler's third law `n = sqrt(GM/a^3)` on the frontend (with `a`
 * in AU and `n` in rad/day).
 */
export const KM3_S2_TO_AU3_DAY2 = 86400 ** 2 / AU_KM ** 3;
/** Convert a velocity in km/day to AU/day. */
export const KM_DAY_TO_AU_DAY = 1 / AU_KM;

/** Convert km to scene units */
export function kmToScene(km: number): number {
	return (km / AU_KM) * AU_SCALE;
}

/** Convert scene units to km */
export function sceneToKm(scene: number): number {
	return (scene / AU_SCALE) * AU_KM;
}

const COS_OBL = Math.cos(EARTH_OBLIQUITY_DEG * (Math.PI / 180));
const SIN_OBL = Math.sin(EARTH_OBLIQUITY_DEG * (Math.PI / 180));

/** A three.js `Vector3` satisfies this, which keeps this module free of three —
 *  it is bundled into the orbit worker, where three has no business. */
export interface Vec3Like {
	x: number;
	y: number;
	z: number;
}

/**
 * Equatorial J2000 → three.js scene frame: rotate about the shared X axis (the
 * vernal equinox) by the obliquity, then send ecliptic X→X, north Z→Y and
 * Y→−Z. That last flip keeps the whole thing a proper rotation (det +1), so
 * chiral quantities like spin axes survive it.
 */
export function equatorialToScene<T extends Vec3Like>(
	xEq: number,
	yEq: number,
	zEq: number,
	out: T
): T;
export function equatorialToScene(xEq: number, yEq: number, zEq: number): Vec3Like;
export function equatorialToScene(xEq: number, yEq: number, zEq: number, out?: Vec3Like): Vec3Like {
	const target = out ?? { x: 0, y: 0, z: 0 };
	target.x = xEq;
	target.y = -yEq * SIN_OBL + zEq * COS_OBL;
	target.z = -(yEq * COS_OBL + zEq * SIN_OBL);
	return target;
}
