/** 1 AU = this many Three.js units */
export const AU_SCALE = 10;
/** 1 AU in km */
export const AU_KM = 149_597_870.7;
/** Mean obliquity of the ecliptic at J2000 (IAU 2006), in degrees. */
export const EARTH_OBLIQUITY_DEG = 23.4392911;
/**
 * Multiply a GM value in km^3/s^2 by this to get AU^3/day^2 — the canonical
 * units for Kepler's third law `n = sqrt(GM/a^3)` on the frontend (with `a`
 * in AU and `n` in rad/day).
 */
export const KM3_S2_TO_AU3_DAY2 = 86400 ** 2 / AU_KM ** 3;
/** Convert km to scene units */

export function kmToScene(km: number): number {
	return (km / AU_KM) * AU_SCALE;
}
