/** CLOSE: too close, revert to point cloud. FULL: halos + trails. CAPPED: in
 *  range for FULL but rejected by the crowding cap. FAR: point cloud. HIDE: hidden. */
export enum VISIBILITY {
	CLOSE = 1,
	FULL = 2,
	CAPPED = 3,
	FAR = 4,
	HIDE = 5
}

/** Distance ratio thresholds (camera distance / moon semi-major axis, both AU).
 *  Tuned for a 27" 1440p monitor; FULL/FAR scaled at runtime by screenScaleFactor. */
/** Viewport height (CSS px) the distance-ratio thresholds were tuned for. */
export const REFERENCE_VIEWPORT_HEIGHT = 1503;

export const PLANETARY_DISTANCE_RATIO_THRESHOLDS = {
	[VISIBILITY.CLOSE]: 0.3,
	[VISIBILITY.FULL]: 20,
	[VISIBILITY.FAR]: 100,
	[VISIBILITY.HIDE]: Infinity
};
export const SYSTEM_DISTANCE_RATIO_THRESHOLDS = {
	[VISIBILITY.CLOSE]: 0.01,
	[VISIBILITY.FULL]: 20,
	[VISIBILITY.FAR]: 100,
	[VISIBILITY.HIDE]: Infinity
};

/** Multiplier applied to the FULL threshold for the currently focused body. */
export const FOCUSED_FULL_MULTIPLIER_MOON = 5;
export const FOCUSED_FULL_MULTIPLIER_SUN_ORBITING = 50;

/** Max number of moons shown at FULL visibility simultaneously. Excess (outermost) are demoted to FAR. */
export const MAX_FULL_MOONS = 40;

/** Moon semi-major axes are multiplied by this for the focus hide threshold,
 *  matching the convention that it reflects full orbital extent (≈2a for
 *  circular moons). Higher = solar system stays visible longer when zoomed in. */
export const FOCUS_HIDE_MOON_MULTIPLIER = 2;

// The scrubbed trajectory craft counts as inside a system within the same
// reach the declutter uses (`systemReachAU`), or its actual SOI reads as
// empty space, planets away from any visible system.
/** Reach of a system whose satellites can't measure one out (Mercury, Venus,
 *  small bodies), as a fraction of its sphere of influence. */
export const TRAVEL_SYSTEM_SOI_FRACTION = 1 / 3;
/** Warm a system's textures this far out (× the entry radius), so entering it
 *  doesn't land on white spheres. */
export const TRAVEL_SYSTEM_PREFETCH_MULTIPLIER = 2;

/** Shared ratio→VISIBILITY mapping used by both moon and planet/spacecraft visibility. */
export function computeVisibilityFromRatio(
	ratio: number,
	thresholds: typeof PLANETARY_DISTANCE_RATIO_THRESHOLDS,
	focusedMultiplier: number,
	isFocused: boolean
): VISIBILITY {
	if (ratio <= thresholds[VISIBILITY.CLOSE]) return VISIBILITY.CLOSE;
	if (ratio <= thresholds[VISIBILITY.FULL] * (isFocused ? focusedMultiplier : 1))
		return VISIBILITY.FULL;
	if (ratio <= thresholds[VISIBILITY.FAR]) return VISIBILITY.FAR;
	return VISIBILITY.HIDE;
}
