/** Switches to catalogue stars before skybox parallax becomes visible. */

/** Starts loading early so nearby nodes are ready before the switch. */
export const PREFETCH_AU = 500;
/** Delays unloading to prevent churn near the prefetch boundary. */
export const RELEASE_AU = 400;
/** Limit magnitude with the camera near its target, as the skybox draws it. */
export const BASE_LIMIT_MAG = 7.5;
/** Past this distance (AU) the starfield takes the sky. */
export const STARS_IN_AU = 2_000;
/** Restores the skybox later to prevent flicker near the switch. */
export const STARS_OUT_AU = 1_800;

/** Keeps the prior state between thresholds to provide hysteresis. */
export function starsTakeSky(distanceAu: number, taken: boolean): boolean {
	if (distanceAu + 1e-9 >= STARS_IN_AU) return true;
	if (distanceAu < STARS_OUT_AU) return false;
	return taken;
}

/**
 * The glow holds the stars fainter than this, from any place. It is the
 * skybox's limit, so the join at 2,000 AU does not move. A dot is drawn to at
 * least this limit, or to the drawn limit where the star budget holds that
 * lower (`dotLimit`), so no light falls between the two. The stars between
 * them count twice, as a dot and in the glow.
 */
export const GLOW_CUT_MAG = BASE_LIMIT_MAG;

/**
 * Distances (pc) from the Sun over which the dots move from the drawn limit's
 * exposure onto the glow's (`dotLimit`). Near the Sun the catalogue is the
 * sky, so its faintest drawn star shows. Far from it, the glow holds the
 * catalogue's light, and a dot that draws to the drawn limit adds that light
 * again as a haze of specks.
 */
export const GLOW_EXPOSURE_FROM_PC = 300;
export const GLOW_EXPOSURE_FULL_PC = 3_000;

/** Share (0 to 1) of the glow's exposure in the dots, with the camera
 *  `fromSunPc` from the Sun: smooth on the log of distance. */
export function glowExposureShare(fromSunPc: number): number {
	const from = Math.log(GLOW_EXPOSURE_FROM_PC);
	const t =
		(Math.log(Math.max(fromSunPc, GLOW_EXPOSURE_FROM_PC)) - from) /
		(Math.log(GLOW_EXPOSURE_FULL_PC) - from);
	const c = Math.min(t, 1);
	return c * c * (3 - 2 * c);
}

/**
 * The limit (mag) of a dot at the glow's exposure, `gain` times the Sun's
 * (`placeGain`). A star at it sends the camera the light of the faintest dot
 * of the Sun's sky, which is the threshold for a dot to show. A fainter star's
 * light stays in the glow alone.
 */
export function glowLimitMag(gain: number): number {
	return BASE_LIMIT_MAG + 2.5 * Math.log10(gain);
}

/**
 * The limit a dot draws to, of the drawn limit `limit`, the share of the
 * glow's exposure `share` (`glowExposureShare`) and the limit at that exposure
 * `glowLimit` (`glowLimitMag`). It is never under the glow's cut, or under the
 * drawn limit where that is lower.
 */
export function dotLimit(limit: number, share: number, glowLimit: number): number {
	const exposed = limit - share * Math.max(limit - glowLimit, 0);
	return Math.max(exposed, Math.min(limit, GLOW_CUT_MAG));
}

/**
 * The drawn limit over which a star of a box can draw, from the box's
 * brightest magnitude (`dotLimit` turned around). The walk of the tree then
 * fetches no box whose dots the glow's exposure hides.
 */
export function boxDrawMag(magnitude: number, share: number, glowLimit: number): number {
	if (magnitude < Math.max(glowLimit, GLOW_CUT_MAG)) return magnitude;
	return share >= 1 ? Infinity : (magnitude - share * glowLimit) / (1 - share);
}

/** Distance (pc) from the Sun past which the zoom's target rises by 5 mag a decade. */
const ZOOM_PC = 1;

/** The walk's target limit (mag) with the camera at `fromSunPc`: the zoom's. */
export function targetLimitMag(fromSunPc: number): number {
	return BASE_LIMIT_MAG + 5 * Math.log10(Math.max(1, fromSunPc / ZOOM_PC));
}
