/**
 * The trajectories on offer, grouped by how the trip is flown.
 *
 * Four kinds of answer end up in one list — a window off the porkchop, a
 * swing-by, an arc held under thrust, a spiral out — and they are not read
 * against each other: a spiral's four years and a Hohmann's nine months answer
 * different questions. Tabbing them keeps each family's rows next to the ones
 * they are actually alternatives to.
 */

import type { OfferedRoute } from './panel.svelte';
import type { RouteOption } from './trip';

export type RouteFamily = 'transfer' | 'gravity-assist' | 'constant-thrust' | 'low-thrust';

/** The three solver profiles and the hand-picked window are all one family: the
 *  same trajectory, read off the same field, at four points on it. */
export function familyOf(profile: RouteOption): RouteFamily {
	switch (profile) {
		case 'constant-thrust':
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
 * The swing-by hunt lands about a second after everything else, and a tab that
 * appears late moves the ones beside it. So it holds its place while it runs
 * rather than being added when it lands — the reader is told there may be one
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
 * else the first that does.
 *
 * Only ever retires a choice, so a swing-by landing under a reader who is
 * reading the spiral does not take them somewhere they did not ask to be.
 */
export function activeFamily(
	tabs: readonly RouteTab[],
	wanted: RouteFamily | null
): RouteFamily | null {
	if (wanted && tabs.some((tab) => tab.family === wanted && !tab.loading)) return wanted;
	return tabs.find((tab) => !tab.loading)?.family ?? null;
}
