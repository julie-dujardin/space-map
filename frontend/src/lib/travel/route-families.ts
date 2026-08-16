/**
 * The trajectories on offer, grouped by how the trip is flown.
 *
 * Four kinds of answer end up in one list — a window off the porkchop, a
 * swing-by, an arc held under thrust, a spiral out — and they aren't read
 * against each other: a spiral's four years and a Hohmann's nine months answer
 * different questions. Tabbing keeps each family's rows next to the ones
 * they're actually alternatives to.
 */

import type { OfferedRoute } from './panel.svelte';
import type { RouteOption } from './trip';

export type RouteFamily = 'transfer' | 'gravity-assist' | 'constant-thrust' | 'low-thrust';

/** The three solver profiles and the hand-picked window are all one family: the
 *  same trajectory, read off the same field, at four points on it. The held arc
 *  makes a family the same way, at four points on the coast. */
export function familyOf(profile: RouteOption): RouteFamily {
	if (profile.startsWith('constant-thrust')) return 'constant-thrust';
	switch (profile) {
		case 'low-thrust':
		case 'gravity-assist':
			return profile;
		default:
			return 'transfer';
	}
}

export interface RouteTab {
	family: RouteFamily;
	/** Still being searched for, so there is nothing to choose in it yet. */
	loading: boolean;
}

/**
 * Which tabs to show, in the order their first route comes back in.
 *
 * The swing-by hunt lands about a second after everything else, and a tab
 * appearing late would move the ones beside it. So it holds its place while
 * running rather than being added on landing — the reader is told one may be
 * coming instead of watching the row of tabs jump.
 */
export function routeTabs(offered: readonly OfferedRoute[], assistSearching: boolean): RouteTab[] {
	const tabs: RouteTab[] = [];
	for (const choice of offered) {
		const family = familyOf(choice.profile);
		if (!tabs.some((tab) => tab.family === family)) tabs.push({ family, loading: false });
	}
	if (assistSearching && !tabs.some((tab) => tab.family === 'gravity-assist')) {
		tabs.push({ family: 'gravity-assist', loading: true });
	}
	return tabs;
}

export function routesIn(
	offered: readonly OfferedRoute[],
	family: RouteFamily | null
): OfferedRoute[] {
	return offered.filter((choice) => familyOf(choice.profile) === family);
}

/**
 * The tab actually showing: the one asked for while it still holds anything,
 * else the first that does. Only ever retires a choice, so a swing-by landing
 * under a reader who is reading the spiral doesn't move them.
 */
export function activeFamily(
	tabs: readonly RouteTab[],
	wanted: RouteFamily | null
): RouteFamily | null {
	if (wanted && tabs.some((tab) => tab.family === wanted && !tab.loading)) return wanted;
	return tabs.find((tab) => !tab.loading)?.family ?? null;
}
