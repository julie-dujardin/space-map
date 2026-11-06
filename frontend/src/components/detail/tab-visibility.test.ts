/**
 * The Planets page has five tabs: the overview, the Solar System, the
 * exoplanets, the pictures and the members. The bar holds four, so on desktop
 * the pictures leave it for the hero's pill. The Structure tab shows for a
 * body's block or a star's Interior row.
 */

import { describe, expect, it } from 'vitest';
import { DRAWER_TABS, type DrawerTab } from '$lib/state/view';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { promoteTabs, structureTabPresent } from './tab-visibility';

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

describe('the Structure tab', () => {
	const layers = [{ role: 'convective_zone', outer_radius_km: 1, composition: [] }];
	const base = { global: null, starInterior: null, isGroupMode: false, isFeatureMode: false };

	it('shows for a star with an interior block, which has no bundle block', () => {
		expect(structureTabPresent({ ...base, starInterior: { layers } })).toBe(true);
	});

	it('does not show for a star without one', () => {
		expect(structureTabPresent(base)).toBe(false);
		expect(structureTabPresent({ ...base, starInterior: { layers: [] } })).toBe(false);
		const star = { id: 'x-1' } as unknown as GlobalObjectData;
		expect(structureTabPresent({ ...base, global: star })).toBe(false);
	});

	it('still shows for a body with a layer model or a named atmosphere', () => {
		const global = { id: 'naif-10', interior: { layers } } as unknown as GlobalObjectData;
		expect(structureTabPresent({ ...base, global })).toBe(true);
		const air = { id: 'naif-606', atmosphere: { structure: {} } } as unknown as GlobalObjectData;
		expect(structureTabPresent({ ...base, global: air })).toBe(true);
	});

	it('never shows on a group or a feature page', () => {
		const starInterior = { layers };
		expect(structureTabPresent({ ...base, starInterior, isGroupMode: true })).toBe(false);
		expect(structureTabPresent({ ...base, starInterior, isFeatureMode: true })).toBe(false);
	});
});
