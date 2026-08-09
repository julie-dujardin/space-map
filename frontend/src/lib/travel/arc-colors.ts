/** The colour a stretch of trajectory is drawn in, in one place so the arc on
 *  the map and the bar under it cannot say different things about the same leg. */

import type { PathArcKind } from '$lib/math/travel/path';
import type { LegKind } from '$lib/math/travel';

export const ARC_COLORS: Record<PathArcKind, string> = {
	cruise: '#7fdbff',
	boost: '#ffb454',
	brake: '#ff8c69'
};

/**
 * The same colours on the timeline's bar, plus the one stretch of a trip the map
 * draws no arc for: aerobraking walks the orbit down over months without going
 * anywhere, so it has a colour here and nothing to colour out there. Green
 * because it is the one leg that costs time instead of propellant.
 */
export const PHASE_COLORS: Partial<Record<LegKind, string>> = {
	...ARC_COLORS,
	aerobrake: '#8fd9a8'
};
