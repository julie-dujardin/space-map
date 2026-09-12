/** The shape of the drawer's tab table, the bar's budget, and what happens
 *  past it. */

import type { Snippet } from 'svelte';
import { DRAWER_TABS, type DrawerTab } from '$lib/state/view';

/** One entry of the drawer's ordered tab table — the single source for the
 *  bar's triggers, the gallery shelf links, the panel bodies and a promoted
 *  tab's header, so none of them can diverge. */
export interface TabItem {
	tab: DrawerTab;
	label: string;
	/** Badge count; tabs whose badge would crowd the bar leave it off. */
	count?: number;
	/** Whether this object has the tab at all. */
	present: boolean;
	/** The panel body. Rendered as a tabpanel under the bar, and on its own
	 *  when the tab is promoted out of it. */
	panel: Snippet;
}

/** Keyed by tab so no tab can be left out of the table: a promoted one takes
 *  both its header and its panel from here. */
export type TabTable = Record<DrawerTab, Omit<TabItem, 'tab'>>;

/** The table as the bar's ordered list. */
export function tabList(table: TabTable): TabItem[] {
	return DRAWER_TABS.map((tab) => ({ tab, ...table[tab] }));
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
