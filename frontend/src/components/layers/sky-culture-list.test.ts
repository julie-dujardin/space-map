import { describe, expect, it } from 'vitest';
import type { SkyCultureEntry } from '$lib/fetch/extrasolar/skycultures';
import { byRegion, cultureName, matchCulture, orderCultures } from './sky-culture-list';

const entry = (key: string, name: string, group: string, figures: number, labels = {}) =>
	({ key, name, group, figures, labels }) as SkyCultureEntry;

const CULTURES = [
	entry('mocovi', 'Mocoví', 'south-america', 12),
	entry('chinese', 'Chinese', 'eastern-asia', 312, { fr: 'Chinois' }),
	entry('modern_iau', 'Modern (IAU)', 'modern', 88)
];

describe('the culture list', () => {
	it('reads the name in the reader language, else the English one', () => {
		expect(cultureName(CULTURES[1], 'fr')).toBe('Chinois');
		expect(cultureName(CULTURES[1], 'de')).toBe('Chinese');
	});

	it('groups by region in the order of the table', () => {
		expect(byRegion(CULTURES, 'en').map((region) => region.group)).toEqual([
			'modern',
			'south-america',
			'eastern-asia'
		]);
	});

	it('sorts by figures, most first', () => {
		expect(orderCultures(CULTURES, 'figures', 'en').map((c) => c.key)).toEqual([
			'chinese',
			'modern_iau',
			'mocovi'
		]);
	});

	it('finds a name typed with no accent, and the English name of a translated one', () => {
		expect(matchCulture(CULTURES[0], 'mocovi', 'en')).toBe(true);
		expect(matchCulture(CULTURES[1], 'chinese', 'fr')).toBe(true);
		expect(matchCulture(CULTURES[1], 'greek', 'fr')).toBe(false);
	});
});
