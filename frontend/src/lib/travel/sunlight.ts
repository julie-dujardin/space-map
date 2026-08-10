/**
 * What sunlight does with distance.
 *
 * A leaf on purpose: the hazard scan needs it and so does the text that reports
 * one, and that text is read by the map's own overlay — which is held by the
 * renderer from the first frame and must not end up importing the trajectory
 * kernel to print a number.
 */

/** Solar irradiance at 1 AU, W/m² (Kopp & Lean 2011). Every threshold in
 *  `hazards.ts` is a multiple of it rather than an absolute figure. */
export const SOLAR_CONSTANT_W_M2 = 1361;

/**
 * Blackbody equilibrium temperature at 1 AU, K.
 *
 * What an unshaded surface with no albedo and no internal heat settles at — the
 * only temperature a trajectory can be said to have, since a real spacecraft's
 * is a fact about its paint and its radiators.
 */
const EQUILIBRIUM_TEMP_1AU_K = 278.6;

/**
 * Sunlight, as a multiple of what the same array or surface sees at 1 AU.
 *
 * One quantity does both distance hazards: past 1 it is heat to be got rid of,
 * under 1 it is power that is no longer there.
 */
export function sunsAt(au: number): number {
	return 1 / (au * au);
}

/** What an unshaded surface settles at, K, at `au` from the Sun. */
export function equilibriumTempK(au: number): number {
	return EQUILIBRIUM_TEMP_1AU_K / Math.sqrt(au);
}
