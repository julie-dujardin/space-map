/** The colour a stretch of trajectory is drawn in, in one place so the arc on
 *  the map and the bar under it cannot say different things about the same leg. */

import type { PathArcKind } from '$lib/math/travel/path';
import type { TimelineKind } from '$lib/travel/timeline';

export const ARC_COLORS: Record<PathArcKind, string> = {
	cruise: '#7fdbff',
	boost: '#ffb454',
	brake: '#ff8c69',
	spiral: '#c9a0ff',
	// A shade darker: the crossing's own spiral wound round a body.
	'spiral-out': '#9b7fd4',
	'spiral-in': '#9b7fd4'
};

/** The same colours on the timeline's bar, plus aerobraking, which walks the
 *  orbit down without going anywhere and so has no arc to draw. Green because
 *  it is the one leg that costs time instead of propellant. */
export const PHASE_COLORS: Partial<Record<TimelineKind, string>> = {
	cruise: ARC_COLORS.cruise,
	boost: ARC_COLORS.boost,
	brake: ARC_COLORS.brake,
	'powered-cruise': ARC_COLORS.spiral,
	'spiral-out': ARC_COLORS['spiral-out'],
	'spiral-in': ARC_COLORS['spiral-in'],
	aerobrake: '#8fd9a8'
};
