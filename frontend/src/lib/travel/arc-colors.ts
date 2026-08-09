/** The colour a stretch of trajectory is drawn in, in one place so the arc on
 *  the map and the bar under it cannot say different things about the same leg. */

import type { PathArcKind } from '$lib/math/travel/path';
import type { LegKind } from '$lib/math/travel';

export const ARC_COLORS: Record<PathArcKind, string> = {
	cruise: '#7fdbff',
	boost: '#ffb454',
	brake: '#ff8c69',
	spiral: '#c9a0ff',
	// The same drive, a shade darker: these two stretches are the crossing's own
	// spiral wound round a body, drawn along the body's path because that is
	// where the craft is.
	'spiral-out': '#9b7fd4',
	'spiral-in': '#9b7fd4'
};

/**
 * The same colours on the timeline's bar, plus the one stretch of a trip the map
 * draws no arc for: aerobraking walks the orbit down over months without going
 * anywhere, so it has a colour here and nothing to colour out there. Green
 * because it is the one leg that costs time instead of propellant.
 */
export const PHASE_COLORS: Partial<Record<LegKind, string>> = {
	cruise: ARC_COLORS.cruise,
	boost: ARC_COLORS.boost,
	brake: ARC_COLORS.brake,
	'powered-cruise': ARC_COLORS.spiral,
	'spiral-out': ARC_COLORS['spiral-out'],
	'spiral-in': ARC_COLORS['spiral-in'],
	aerobrake: '#8fd9a8'
};
