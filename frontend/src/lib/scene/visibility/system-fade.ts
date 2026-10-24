/** Uses apparent size so the switch is resolution-independent. */

import { AU_SCALE } from '$lib/math/units';

/** Neptune defines the visible planetary system's radius. */
const SYSTEM_RADIUS_AU = 30.07;
/** Hides planets before the far-view reference zoom. */
export const SYSTEM_OUT_PX = 4.3;
/** Restores planets later to prevent flicker near the switch. */
export const SYSTEM_IN_PX = 4.75;

/** The diameter of Neptune's orbit on screen, CSS px. */
export function systemDiameterPx(
	distanceScene: number,
	viewportPx: number,
	fovDeg: number
): number {
	const pxPerRad = viewportPx / 2 / Math.tan((fovDeg * Math.PI) / 360);
	return ((2 * SYSTEM_RADIUS_AU * AU_SCALE) / distanceScene) * pxPerRad;
}

/** Keeps the prior state between thresholds to provide hysteresis. */
export function systemShown(
	distanceScene: number,
	viewportPx: number,
	fovDeg: number,
	shown: boolean
): boolean {
	const px = systemDiameterPx(distanceScene, viewportPx, fovDeg);
	if (px < SYSTEM_OUT_PX) return false;
	if (px > SYSTEM_IN_PX) return true;
	return shown;
}
