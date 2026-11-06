/**
 * The glow's exposure. A target holds surface brightness, in flux of M = 0 at
 * 10 pc per sr. A screen value is that times the exposure.
 *
 * The exposure is a function of the camera's place alone, never of the sky it
 * sees, so a pose always draws the same and nothing that loads changes it.
 *
 * At the Sun it is the stars' at the skybox's limit, so the band sits at the
 * level of the sky it takes over from. The reference pixel is fixed: the sky has
 * one brightness at any window height, while a dot takes more of a small window.
 *
 * Inside the disc the dots grow brighter as more stars draw. A gain by place
 * keeps the band readable among them there. With a model, the gain also
 * follows the distance to the Galactic centre, as the sky's mean brightness
 * falls with it, and grows far outside the Galaxy. So the model's Galaxy holds
 * the view. Away from the Sun the dots take this exposure too (`band.ts`), so
 * a dot draws the light the glow would give its star.
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
/** Gain (mag) by place, deep in the disc. There the dots grow brighter as more
 *  stars draw, and this gain keeps the band readable among them. */
export const PLACE_GAIN_MAG = 1.6;
/** Height (pc) above the plane at which the gain in the disc is half, in mag:
 *  from above the disc more would wash out the stars. */
export const PLACE_HEIGHT_PC = 4_000;
/** Gain (mag) by place far outside the Galaxy, which rises over `FAR_FROM_PC`
 *  to `FAR_FULL_PC` from the Galactic centre. The disc ends near the first. */
export const OUTSIDE_GAIN_MAG = 1.5;
/** Distances (pc) from the Galactic centre over which the gain far outside
 *  rises. Past the second it holds, so the Galaxy keeps its brightness as it
 *  gets smaller. */
export const FAR_FROM_PC = 16_000;
export const FAR_FULL_PC = 30_000;

/** Where the stars take the sky from the skybox (pc). */
const JOIN_PC = (STARS_IN_AU * AU_KM) / KM_PER_PC;
/**
 * Distance (pc) from the Sun at which the march has the whole glow. Nearer, the
 * sky from the Sun shares it (`joinShare`). Within it the march's own view
 * from the camera moves from the view at the Sun by under 1% in the mean
 * toward the centre, the anticentre, Carina and the LMC, and by 4% toward the
 * north pole.
 */
export const JOIN_FULL_PC = 10;

/**
 * The march's share of the glow, by the camera's distance `fromSunPc` from the
 * Sun: 0 at the join and 1 at `JOIN_FULL_PC`, smooth on the log of distance.
 * The rest is the sky from the Sun: its skybox blurred and its emission map.
 * So the sky past the join starts as the one inside it and turns into the
 * march's as the view moves.
 */
export function joinShare(fromSunPc: number): number {
	const t = Math.log(Math.max(fromSunPc, JOIN_PC) / JOIN_PC) / Math.log(JOIN_FULL_PC / JOIN_PC);
	const c = Math.min(t, 1);
	return c * c * (3 - 2 * c);
}

/** Share of the gain far outside, by distance from the Galactic centre `centre`. */
function outsideShare(at: Vec3, centre: Vec3): number {
	const d = Math.hypot(at[0] - centre[0], at[1] - centre[1], at[2] - centre[2]);
	const t = Math.min(Math.max((d - FAR_FROM_PC) / (FAR_FULL_PC - FAR_FROM_PC), 0), 1);
	return t * t * (3 - 2 * t);
}

/** Powers of the distance from the Galactic centre in the gain by place,
 *  farther from the centre than the Sun and nearer to it. Away from the
 *  centre the sky's mean brightness falls about as that distance; toward it,
 *  it rises more slowly. Past `FAR_FULL_PC` the gain holds, so the Galaxy keeps its surface
 *  brightness as it gets smaller. */
export const CENTRE_FAR_POWER = 1;
export const CENTRE_NEAR_POWER = 0.5;
/** Least gain from the distance to the centre, in the bulge. */
export const CENTRE_LEAST_GAIN = 0.25;

/**
 * Gain over the Sun's exposure from the camera's place `at` (pc from the Sun, on
 * nest axes, so z is height above the plane). It is 1 at the join and inside
 * it, so the join does not move, and it has no step past it.
 *
 * It rises with the march's share (`joinShare`). Toward the inner Galaxy the
 * march holds less light than the sky from the Sun (0.41 of it toward the
 * centre), so a gain that rose later would let the sky dim and then brighten
 * on a zoom out. Rising together, the frame only brightens.
 *
 * With a model, `centre` is its Galactic centre, and two more parts act: the
 * distance to the centre, so the gain falls toward the centre and rises away
 * from it, and a part far outside the Galaxy. Without a model it is null, and
 * the catalogue's glow, a ball about the Sun, takes the gain in the disc only.
 */
export function placeGain(at: Vec3, centre: Vec3 | null): number {
	const rise = joinShare(Math.hypot(at[0], at[1], at[2]));
	const up = at[2] / PLACE_HEIGHT_PC;
	const disc = 10 ** (0.4 * ((PLACE_GAIN_MAG * rise) / (1 + up * up)));
	if (!centre) return disc;
	const outside = 10 ** (0.4 * OUTSIDE_GAIN_MAG * outsideShare(at, centre));
	const fromCentre = Math.hypot(at[0] - centre[0], at[1] - centre[1], at[2] - centre[2]);
	const ratio = Math.min(fromCentre, FAR_FULL_PC) / Math.hypot(centre[0], centre[1], centre[2]);
	const power = ratio >= 1 ? CENTRE_FAR_POWER : CENTRE_NEAR_POWER;
	const byCentre = Math.max(ratio ** power, CENTRE_LEAST_GAIN) ** rise;
	return disc * outside * byCentre;
}
