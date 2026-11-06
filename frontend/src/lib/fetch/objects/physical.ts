import type { GlobalObjectData } from './object-data';

/** The body's mean radius (km): the mean of `radii`, else half the SBDB
 *  diameter. The export writes `radii` only where it outranks SBDB. */
export function meanRadiusKm(global: GlobalObjectData | null): number | null {
	const radii = global?.radii;
	if (radii) return (radii.a + radii.b + radii.c) / 3;
	const diameter = global?.sbdb?.diameter;
	return diameter ? diameter / 2 : null;
}

/** Sidereal spin from the IAU pole model where one is ingested, else SBDB's
 *  hours. */
export function rotationPeriodDays(global: GlobalObjectData | null): number | null {
	const w1 = global?.orientation?.w1;
	if (w1) return 360 / Math.abs(w1);
	const hours = global?.sbdb?.rot_per;
	return hours ? hours / 24 : null;
}
