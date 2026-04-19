/** 1 AU = this many Three.js units */
export const AU_SCALE = 10;
/** 1 AU in km */
export const AU_KM = 149_597_870.7;
/** Mean obliquity of the ecliptic at J2000 (IAU 2006), in degrees. */
export const EARTH_OBLIQUITY_DEG = 23.4392911;
/** Convert km to scene units */

export function kmToScene(km: number): number {
	return (km / AU_KM) * AU_SCALE;
}
