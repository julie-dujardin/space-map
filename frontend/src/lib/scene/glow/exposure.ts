/**
 * The glow's exposure. A map holds surface brightness, in flux of M = 0 at
 * 10 pc per sr. A screen value is that times the exposure.
 *
 * The exposure follows the mean brightness of the map, as an eye does: slowly,
 * and only part of the way, so a galaxy seen small from far away stays dimmer
 * than the band from inside. A map covers the whole sphere, so its mean changes
 * when the camera moves, never when it turns. Nothing that loads changes it.
 *
 * At the Sun the map's mean is the reference, so the exposure there is the
 * stars' at the skybox's limit, and the band sits at the level of the sky it
 * takes over from. The reference pixel is fixed: the sky has one brightness at
 * any window height, while a dot takes more of a small window.
 *
 * Inside the disc the mean hardly changes, but the dots grow brighter as more
 * stars draw. A gain set by the camera's place keeps the band readable among
 * them there. It reads nothing that loads, so it holds still while nodes do.
 *
 * `eye.ts` runs the eye's law on the GPU.
 */

import { AU_KM, KM_PER_PC } from '$lib/math/units';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { BASE_LIMIT_MAG, STARS_IN_AU } from '$lib/scene/starfield/band';

/** Linear light of a star at the limit: core 0.06, over a dot of 0.975 px². */
export const LIGHT_AT_LIMIT = 0.0585;
/** Solid angle (sr) of the reference pixel: 60° over 900 CSS px. */
export const REFERENCE_PIXEL_SR = ((2 * Math.tan(Math.PI / 6)) / 900) ** 2;
/** Screen value of a surface brightness of one, at the Sun. */
export const SUN_EXPOSURE = LIGHT_AT_LIMIT * REFERENCE_PIXEL_SR * 10 ** (0.4 * BASE_LIMIT_MAG);
/** Share of a change in mean brightness, in log, that the exposure takes back. */
export const ADAPT_POWER = 0.5;
/** Most and least gain over the exposure at the Sun. */
export const MAX_GAIN = 40;
export const MIN_GAIN = 0.25;
/** Time (ms) of each of the eye's two stages. */
export const ADAPT_MS = 500;
/** Time (ms) after a new mean in which the eye covers all but 0.05% of the change. */
export const ADAPT_REST_MS = 10 * ADAPT_MS;
/** The eye stops and takes its target once both stages are this share from it:
 *  a last step this small does not show, and the frame loop can rest. */
export const ADAPT_CLOSE = 0.005;

/** Gain (mag) by place, deep in the disc. There the dots grow brighter as more
 *  stars draw, and this gain keeps the band readable among them. */
export const PLACE_GAIN_MAG = 1.6;
/** Distance (pc) past the join at which the gain by place is half its rise. */
export const PLACE_RISE_PC = 8;
/** Height (pc) above the plane at which the gain by place is half, in mag: from
 *  above the disc the eye brightens the glow, and more would wash out the stars. */
export const PLACE_HEIGHT_PC = 4_000;
/** Where the stars take the sky from the skybox (pc). */
const JOIN_PC = (STARS_IN_AU * AU_KM) / KM_PER_PC;

/**
 * Gain over the eye's from the camera's place `at` (pc from the Sun, on nest
 * axes, so z is height above the plane). It is 1 at the join and inside it, so
 * the join does not move, and rises with no step or kink past it.
 */
export function placeGain(at: Vec3): number {
	const out = Math.max(Math.hypot(at[0], at[1], at[2]) - JOIN_PC, 0) / PLACE_RISE_PC;
	const rise = (out * out) / (1 + out * out);
	const up = at[2] / PLACE_HEIGHT_PC;
	return 10 ** ((0.4 * PLACE_GAIN_MAG * rise) / (1 + up * up));
}

/** The gain over the Sun's exposure that a map of mean brightness `mean` asks for. */
export function adaptedGain(mean: number, sunMean: number): number {
	if (!(mean > 0) || !(sunMean > 0)) return 1;
	return Math.min(Math.max((sunMean / mean) ** ADAPT_POWER, MIN_GAIN), MAX_GAIN);
}

/** Share of the eye's distance to its target that a frame of `dtMs` keeps. */
export function eyeKeep(dtMs: number): number {
	return Math.exp(-Math.max(dtMs, 0) / ADAPT_MS);
}
