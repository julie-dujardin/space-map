/** The colour a named trajectory is drawn in. Its row, its mark on the
 *  launch-window field and its dot on the cruise slider all use it. */

import type { RouteOption } from '$lib/travel/trip';

/** Where a named trajectory sits on the trade between time and Δv. Both
 *  families offer the same three points, so both use the same three colours. */
export type RouteTier = 'fast' | 'balanced' | 'efficient';

export function routeTier(profile: RouteOption): RouteTier | null {
	switch (profile) {
		case 'fast':
		case 'constant-thrust':
			return 'fast';
		case 'balanced':
		case 'constant-thrust-balanced':
			return 'balanced';
		case 'efficient':
		case 'constant-thrust-efficient':
			return 'efficient';
		default:
			return null;
	}
}

/**
 * Mid-palette and the same shade in both themes, like the hazard colours. The
 * three must stay apart from each other and legible on either ground.
 */
export const TIER_MARK: Record<RouteTier, string> = {
	fast: 'bg-orange-500',
	balanced: 'bg-emerald-500',
	efficient: 'bg-blue-500'
};

/** The arc set by hand takes the plain mark. The reader placed it. The panel
 *  does not name it. */
const BY_HAND_MARK = 'bg-foreground';

/**
 * The mark a trajectory carries, as a background class.
 *
 * Null where a family offers one trajectory. A colour there would show a
 * choice that does not exist.
 */
export function routeMark(profile: RouteOption): string | null {
	const tier = routeTier(profile);
	if (tier) return TIER_MARK[tier];
	return profile === 'custom' || profile === 'constant-thrust-custom' ? BY_HAND_MARK : null;
}
