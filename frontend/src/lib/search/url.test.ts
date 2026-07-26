import { describe, it, expect } from 'vitest';
import { serializeSearchSuffix, parseSearchSuffix, type SearchUrlState } from './url';

const base: SearchUrlState = {
	query: '',
	filters: {},
	sort: 'relevance',
	reverse: false,
	page: 1
};

/** Round-trip a state through serialize → parse, reading the suffix as query params. */
function roundTrip(s: SearchUrlState): SearchUrlState | null {
	const suffix = serializeSearchSuffix(s);
	return parseSearchSuffix(new URLSearchParams(suffix.replace(/^&/, '')));
}

describe('serializeSearchSuffix', () => {
	it('is empty when nothing is active', () => {
		expect(serializeSearchSuffix(base)).toBe('');
		expect(serializeSearchSuffix(null)).toBe('');
		expect(serializeSearchSuffix({ ...base, query: '   ' })).toBe('');
	});

	it('encodes a bare query', () => {
		expect(serializeSearchSuffix({ ...base, query: 'mons olympus' })).toBe('&q=mons%20olympus');
	});

	it('groups facets into f= with bare bool flags', () => {
		const s = { ...base, filters: { type: ['moon', 'comet'], groups: ['country-us'], neo: true } };
		expect(serializeSearchSuffix(s)).toBe('&f=type:moon,comet;groups:country-us;neo');
	});

	it('omits default sort and page, emits dir only when reversed', () => {
		expect(serializeSearchSuffix({ ...base, query: 'x', sort: 'relevance', page: 1 })).toBe('&q=x');
		expect(
			serializeSearchSuffix({ ...base, query: 'x', sort: 'size', reverse: true, page: 3 })
		).toBe('&q=x&sort=size&dir=desc&page=3');
	});
});

describe('parseSearchSuffix', () => {
	it('returns null when no search is encoded', () => {
		expect(parseSearchSuffix(new URLSearchParams(''))).toBeNull();
		expect(parseSearchSuffix(new URLSearchParams('at=now,1,2,3'))).toBeNull();
	});

	it('round-trips a full state', () => {
		const s: SearchUrlState = {
			query: 'phobos',
			filters: {
				type: ['moon'],
				featureType: ['AA'],
				featureBody: ['naif-499'],
				featureQuad: ['mc01'],
				moonHost: ['naif-599'],
				moonClass: ['planetary'],
				groups: ['country-us'],
				pha: true
			},
			sort: 'brightness',
			reverse: true,
			page: 2
		};
		expect(roundTrip(s)).toEqual(s);
	});

	it('ignores unknown facet tokens and invalid sorts', () => {
		const parsed = parseSearchSuffix(new URLSearchParams('q=x&f=bogus:1;type:moon&sort=nope'));
		expect(parsed).toEqual({
			query: 'x',
			filters: { type: ['moon'] },
			sort: 'relevance',
			reverse: false,
			page: 1
		});
	});

	it('drops dir when sort is relevance', () => {
		const parsed = parseSearchSuffix(new URLSearchParams('q=x&dir=desc'));
		expect(parsed?.reverse).toBe(false);
	});
});

describe('range facets', () => {
	it('serializes both bounds and open-ended bounds', () => {
		expect(
			serializeSearchSuffix({ ...base, filters: { ranges: { diameter: { min: 10, max: 100 } } } })
		).toBe('&f=diameter:10..100');
		expect(
			serializeSearchSuffix({ ...base, filters: { ranges: { magnitude: { max: 15 } } } })
		).toBe('&f=mag:..15');
		expect(
			serializeSearchSuffix({ ...base, filters: { ranges: { inception: { min: 1990 } } } })
		).toBe('&f=date:1990..');
	});

	it('skips a range with no bounds set', () => {
		expect(serializeSearchSuffix({ ...base, filters: { ranges: { diameter: {} } } })).toBe('');
	});

	it('round-trips ranges alongside other facets', () => {
		const s: SearchUrlState = {
			...base,
			filters: {
				type: ['asteroid'],
				ranges: { diameter: { min: 1, max: 50 }, inception: { min: 2000 } },
				neo: true
			}
		};
		expect(roundTrip(s)).toEqual(s);
	});

	it('parses a negative magnitude bound', () => {
		const parsed = parseSearchSuffix(new URLSearchParams('f=mag:-5..0'));
		expect(parsed?.filters.ranges?.magnitude).toEqual({ min: -5, max: 0 });
	});

	it('ignores a malformed range (no ..)', () => {
		expect(parseSearchSuffix(new URLSearchParams('f=diameter:10'))).toBeNull();
	});
});
