/**
 * How a column of dust, as A0 at 550 nm, acts on a star.
 *
 * The law is the curve of Zhang, Green & Rix 2023, which also scales the nest.
 * `K_G` is that curve over the Gaia DR3 G passband (Riello et al. 2021, through
 * the SVO filter service) for a 5,000 K blackbody and a small column. It spans
 * 0.73 at 3,500 K to 1.04 at 20,000 K, and falls to 0.75 at A0 = 3.
 * `K_RGB` is the curve at the sRGB primaries: 612, 549 and 464 nm.
 * `space-map-cache/milky-way-3d/scripts/dust_extinction_coeffs.py` makes them.
 *
 * Across the star colours (`starfield/colour.ts`) these factors move a star
 * along the blackbody locus to within 10%. Past the blue end of the locus they
 * would give a colour that no star has, so red and green stop there.
 */

export const K_G = 0.825;
export const K_RGB: readonly [number, number, number] = [0.863, 1.004, 1.273];

/** The bluest BP−RP of a star, and the BP−RP that one A0 at 550 nm adds. */
export const BLUEST = -0.3;
export const REDDENING = 0.447;
/** The brightest absolute G of any real star. Past it a column is a fit error. */
export const BRIGHTEST_M0 = -10;
/** A bound in the vertex attribute is a byte that spans 0 to this many A0. */
export const BOUND_MAX = 16;

/**
 * The most A0 a star can gain from a camera that sees less dust than the Sun.
 * It cannot gain more than its colour shows it lost, nor pass `BRIGHTEST_M0`.
 * With no colour it gains none. `glow/light.py` holds the same law, because the
 * grid takes out exactly this much dust.
 */
export function dustBound(bpRp: number, mag: number): number {
	const bound = Math.min((bpRp - BLUEST) / REDDENING, (mag - BRIGHTEST_M0) / K_G);
	// A NaN colour or magnitude fails the test and gives 0.
	return bound > 0 ? bound : 0;
}

/** The bounds of stars as bytes, for a normalised vertex attribute. */
export function dustBounds(
	bpRp: ArrayLike<number>,
	mag: ArrayLike<number>,
	out: Uint8Array
): Uint8Array {
	for (let i = 0; i < bpRp.length; i++) {
		out[i] = Math.round((Math.min(dustBound(bpRp[i], mag[i]), BOUND_MAX) / BOUND_MAX) * 255);
	}
	return out;
}

/** The bound in A0 of a byte of {@link dustBounds}. */
export const decodeBound = (byte: number): number => (byte / 255) * BOUND_MAX;

/** 0.4 ln 10: magnitudes to a natural-log flux factor. */
export const MAG_LN = 0.4 * Math.LN10;

/** Least red and green against blue. The hottest star in the colour table is
 *  (0.58, 0.67, 1). These stay under it, so a table colour never changes. */
export const BLUE_END: readonly [number, number] = [0.57, 0.66];

/** The colour of a star behind a column change `dust`. A star that gains light
 *  can pass 1 in a channel, so the largest channel stays at 1 or under. */
export const DUST_COLOUR_GLSL = /* glsl */ `
vec3 dustColour(vec3 colour, highp float dust) {
	vec3 seen = colour * exp(dust * vec3(${K_RGB.map((k) => (-MAG_LN * (k - K_G)).toFixed(5)).join(', ')}));
	seen.rg = max(seen.rg, seen.b * vec2(${BLUE_END.map((x) => x.toFixed(2)).join(', ')}));
	return seen / max(max(seen.r, max(seen.g, seen.b)), 1.0);
}
`;
