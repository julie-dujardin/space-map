/** Uses apparent size so the switch is resolution-independent. */

import { AU_SCALE } from '$lib/math/units';

/** Neptune defines the visible planetary system's radius. */
const SYSTEM_RADIUS_AU = 30.07;
/** Hides planets before the far-view reference zoom. */
export const SYSTEM_OUT_PX = 4.3;
/** Restores planets later to prevent flicker near the switch. */
export const SYSTEM_IN_PX = 4.75;

function pxPerRad(viewportPx: number, fovDeg: number): number {
	return viewportPx / 2 / Math.tan((fovDeg * Math.PI) / 360);
}

/** The diameter on screen (CSS px) of a system of radius `radiusAU`:
 *  Neptune's orbit, or another star's outer orbit. */
export function systemDiameterPx(
	distanceScene: number,
	viewportPx: number,
	fovDeg: number,
	radiusAU = SYSTEM_RADIUS_AU
): number {
	return ((2 * radiusAU * AU_SCALE) / distanceScene) * pxPerRad(viewportPx, fovDeg);
}

/** The distance (scene units) from which a system of radius `radiusAU` shows. */
export function systemShownWithin(radiusAU: number, viewportPx: number, fovDeg: number): number {
	return ((2 * radiusAU * AU_SCALE) / SYSTEM_IN_PX) * pxPerRad(viewportPx, fovDeg);
}

/** Keeps the prior state between thresholds to provide hysteresis. */
export function systemShown(
	distanceScene: number,
	viewportPx: number,
	fovDeg: number,
	shown: boolean,
	radiusAU = SYSTEM_RADIUS_AU
): boolean {
	const px = systemDiameterPx(distanceScene, viewportPx, fovDeg, radiusAU);
	if (px < SYSTEM_OUT_PX) return false;
	if (px > SYSTEM_IN_PX) return true;
	return shown;
}
