/**
 * Zoomed far out, the solar system is a few pixels across, and only the Sun
 * draws. The size on screen sets the switch, so a phone, a 1080p screen and a
 * 4K screen switch at the same look.
 */

import { AU_SCALE } from '$lib/math/units';

/** Neptune's semi-major axis (AU): the radius of the planetary system. */
const SYSTEM_RADIUS_AU = 30.07;
/** Diameter (CSS px) of Neptune's orbit at which only the Sun is left. It is
 *  Julie's zoom 1.8455e5 (18,455 AU) on a view 1080 px tall. */
export const SYSTEM_HIDDEN_PX = 3.05;
/** Diameter (CSS px) at which the planetary system starts to fade out. */
export const SYSTEM_FADE_PX = 6.1;

/** The diameter of Neptune's orbit on screen, CSS px. */
export function systemDiameterPx(
	distanceScene: number,
	viewportPx: number,
	fovDeg: number
): number {
	const pxPerRad = viewportPx / 2 / Math.tan((fovDeg * Math.PI) / 360);
	return ((2 * SYSTEM_RADIUS_AU * AU_SCALE) / distanceScene) * pxPerRad;
}

/** The planetary system's share of the view: 1 draws it, 0 leaves the Sun
 *  alone. `distanceScene` is the camera's distance from the barycentre. */
export function systemShare(distanceScene: number, viewportPx: number, fovDeg: number): number {
	const px = systemDiameterPx(distanceScene, viewportPx, fovDeg);
	const t = Math.log(px / SYSTEM_HIDDEN_PX) / Math.log(SYSTEM_FADE_PX / SYSTEM_HIDDEN_PX);
	const c = Math.min(Math.max(t, 0), 1);
	return c * c * (3 - 2 * c);
}
