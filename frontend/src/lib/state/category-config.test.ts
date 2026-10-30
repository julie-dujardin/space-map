/**
 * A link from the Solar System to the Planets page opens its Solar System tab;
 * no other page has one.
 */

import { describe, expect, it } from 'vitest';
import { CAT_DWARF_PLANETS, CAT_MOONS, CAT_PLANETS } from '$lib/fetch/groups/registry';
import { categoryConfig, solarSystemTab } from './category-config';

describe('solarSystemTab', () => {
	it('opens the Planets page on its Solar System tab', () => {
		expect(solarSystemTab(CAT_PLANETS)).toBe('solar-system');
	});

	it('opens every other page on its overview', () => {
		expect(solarSystemTab(CAT_MOONS)).toBeUndefined();
		expect(solarSystemTab(CAT_DWARF_PLANETS)).toBeUndefined();
		expect(solarSystemTab('planet-gas-giant')).toBeUndefined();
	});
});

describe('the Planets page', () => {
	it('lists its members on a tab, since the overview names only some', () => {
		const cfg = categoryConfig({ kind: 'group', slug: CAT_PLANETS });
		expect(cfg.membersShownInFull).toBe(false);
		expect(cfg.crossRefs).toBe(false);
	});
});
