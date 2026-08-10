import { describe, expect, it } from 'vitest';
import type { Route } from '$lib/math/travel';
import type { OfferedRoute } from './panel.svelte';
import type { RouteOption } from './trip';
import { activeFamily, familyOf, routeTabs, routesIn } from './route-families';

/** Only the profile is read here, so the trajectory itself can be a stand-in. */
function offer(...profiles: RouteOption[]): OfferedRoute[] {
	return profiles.map((profile) => ({ profile, route: {} as Route }));
}

describe('familyOf', () => {
	it('keeps the three solver profiles and the hand-picked window together', () => {
		for (const profile of ['fast', 'balanced', 'efficient', 'custom'] as RouteOption[]) {
			expect(familyOf(profile)).toBe('transfer');
		}
	});

	it('gives every other way of flying one of its own', () => {
		expect(familyOf('gravity-assist')).toBe('gravity-assist');
		expect(familyOf('constant-thrust')).toBe('constant-thrust');
		expect(familyOf('low-thrust')).toBe('low-thrust');
	});
});

describe('routeTabs', () => {
	it('lists a family once, in the order it first comes back', () => {
		const tabs = routeTabs(offer('constant-thrust', 'fast', 'balanced', 'gravity-assist'), false);
		expect(tabs.map((tab) => tab.family)).toEqual([
			'constant-thrust',
			'transfer',
			'gravity-assist'
		]);
		expect(tabs.every((tab) => !tab.loading)).toBe(true);
	});

	it('holds a place for the swing-by while the hunt runs', () => {
		const tabs = routeTabs(offer('fast'), true);
		expect(tabs.map((tab) => tab.family)).toEqual(['transfer', 'gravity-assist']);
		expect(tabs[1].loading).toBe(true);
	});

	// The hunt is still marked as running for as long as the state says so, but a
	// tab with a route in it is a tab you can open.
	it('does not mark a swing-by that has already landed as loading', () => {
		const tabs = routeTabs(offer('fast', 'gravity-assist'), true);
		expect(tabs).toHaveLength(2);
		expect(tabs[1].loading).toBe(false);
	});
});

describe('routesIn', () => {
	it('gathers the whole transfer family and nothing else', () => {
		const offered = offer('constant-thrust', 'fast', 'efficient', 'custom', 'gravity-assist');
		expect(routesIn(offered, 'transfer').map((choice) => choice.profile)).toEqual([
			'fast',
			'efficient',
			'custom'
		]);
		expect(routesIn(offered, 'constant-thrust')).toHaveLength(1);
		expect(routesIn(offered, null)).toHaveLength(0);
	});
});

describe('activeFamily', () => {
	const tabs = routeTabs(offer('low-thrust', 'fast'), true);

	it('keeps the tab that was asked for', () => {
		expect(activeFamily(tabs, 'transfer')).toBe('transfer');
	});

	it('falls back to the first tab holding anything', () => {
		expect(activeFamily(tabs, null)).toBe('low-thrust');
		// Asked for the swing-by while it is still being searched for.
		expect(activeFamily(tabs, 'gravity-assist')).toBe('low-thrust');
		// Asked for a tab that stopped being offered.
		expect(activeFamily(tabs, 'constant-thrust')).toBe('low-thrust');
	});

	it('has nothing to show when nothing is offered', () => {
		expect(activeFamily([], 'transfer')).toBe(null);
		expect(activeFamily(routeTabs([], true), null)).toBe(null);
	});
});
