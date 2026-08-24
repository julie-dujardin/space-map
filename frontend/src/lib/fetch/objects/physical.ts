import type { GlobalObjectData } from './object-data';

/** Back to kilometres from whichever size source the body publishes: the mean
 *  of the radii triple, a Wikidata radius, else an SBDB diameter. */
export function meanRadiusKm(global: GlobalObjectData | null): number | null {
	const radii = global?.radii;
	if (radii) return (radii.a + radii.b + radii.c) / 3;
	const radius = global?.wikidata?.radius;
	if (radius) {
		if (radius.unit === 'kilometre') return radius.value;
		if (radius.unit === 'metre') return radius.value / 1000;
		return null;
	}
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
