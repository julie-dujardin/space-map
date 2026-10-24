/** Switches to catalogue stars before skybox parallax becomes visible. */

/** Starts loading early so nearby nodes are ready before the switch. */
export const PREFETCH_AU = 500;
/** Delays unloading to prevent churn near the prefetch boundary. */
export const RELEASE_AU = 400;
/** Past this distance (AU) the starfield takes the sky. */
export const STARS_IN_AU = 2_000;
/** Restores the skybox later to prevent flicker near the switch. */
export const STARS_OUT_AU = 1_800;

/** Keeps the prior state between thresholds to provide hysteresis. */
export function starsTakeSky(distanceAu: number, taken: boolean): boolean {
	if (distanceAu > STARS_IN_AU) return true;
	if (distanceAu < STARS_OUT_AU) return false;
	return taken;
}
