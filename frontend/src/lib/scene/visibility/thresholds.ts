/*
 * Visibility options:
 * CLOSE: too close to show everything, revert to point cloud.
 * FULL: show halos and trails.
 * CAPPED: In range for FULL but rejected by the crowding cap — point cloud by default, minimized halo when hideCappedMoonLabels=true.
 * FAR: point cloud.
 * HIDE: hide entirely.
 */
export enum VISIBILITY {
	CLOSE = 1,
	FULL = 2,
	CAPPED = 3,
	FAR = 4,
	HIDE = 5
}

/*
 * Distance ratio thresholds for visibility levels.
 * Ratio is (camera distance to focused body / moon semi-major axis), both in AU.
 * These were tuned for a 27" 1440p monitor; FULL and FAR are scaled at runtime by screenScaleFactor.
 */
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
export const MAX_FULL_MOONS = 20;

/**
 * Moon semi-major axes are multiplied by this when contributing to the
 * focus hide threshold, matching the convention that the threshold reflects
 * a satellite's full orbital extent (≈ 2a for circular moons; raw distance
 * for eccentric probes). Higher value = solar system stays visible longer
 * after zooming into a planet (bigger overlap).
 */
export const FOCUS_HIDE_MOON_MULTIPLIER = 2;

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
