/**
 * The Planets page has five tabs: the overview, the Solar System, the
 * exoplanets, the pictures and the members. The bar holds four, so on desktop
 * the pictures leave it for the hero's pill.
 */

import { describe, expect, it } from 'vitest';
import { DRAWER_TABS, type DrawerTab } from '$lib/state/view';
import { promoteTabs } from './tab-visibility';

const PLANETS_PAGE: DrawerTab[] = ['overview', 'solar-system', 'exoplanets', 'images', 'members'];

function present(tabs: DrawerTab[]): Record<DrawerTab, boolean> {
	return Object.fromEntries(DRAWER_TABS.map((t) => [t, tabs.includes(t)])) as Record<
		DrawerTab,
		boolean
	>;
}

describe('the tabs of the Planets page', () => {
	it('come right after the overview', () => {
		expect(DRAWER_TABS.slice(0, 3)).toEqual(['overview', 'solar-system', 'exoplanets']);
	});

	it('send the pictures to the hero on desktop, and keep them in the bar on a phone', () => {
		expect([...promoteTabs(present(PLANETS_PAGE), PLANETS_PAGE.length, false)]).toEqual(['images']);
		expect(promoteTabs(present(PLANETS_PAGE), PLANETS_PAGE.length, true).size).toBe(0);
	});
});
