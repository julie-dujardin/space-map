/** The tab bar's budget and what happens past it. */

import type { DrawerTab } from '$lib/state/view';

/** One entry of the drawer's ordered tab table — the single source for the
 *  bar's triggers and the gallery shelf links, so their labels can't diverge. */
export interface TabItem {
	tab: DrawerTab;
	label: string;
	/** Badge count; tabs whose badge would crowd the bar leave it off. */
	count?: number;
}

// Past this budget, tabs promote to whatever in the overview already leads
// to them (the probes strip, the hero pill for Images) — a tab with no such
// way in can't be listed. Images leaves first: its pill sits in the hero.
export const TAB_BUDGET = 4;
export const PROMOTABLE: readonly DrawerTab[] = ['images', 'probes'];

// Shelves named after an aspect of this object rather than a subject of their
// own: the tab that covers the same ground is where the rest of it is.
export const SHELF_TABS: Record<string, Exclude<DrawerTab, 'overview'>> = {
	rings: 'rings',
	atmosphere: 'structure',
	interior: 'structure',
	features: 'features',
	moons: 'members'
};

// Mobile scrolls its bar instead — the tabs stay where a thumb expects them.
export function promoteTabs(
	tabPresent: Record<DrawerTab, boolean>,
	tabCount: number,
	isMobile: boolean
): Set<DrawerTab> {
	const promoted = new Set<DrawerTab>();
	if (isMobile) return promoted;
	let inBar = tabCount;
	for (const tab of PROMOTABLE) {
		if (inBar <= TAB_BUDGET) break;
		if (!tabPresent[tab]) continue;
		promoted.add(tab);
		inBar--;
	}
	return promoted;
}
