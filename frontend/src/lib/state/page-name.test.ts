import { describe, expect, it, vi } from 'vitest';

const { live, fetchObjectDetail } = vi.hoisted(() => ({
	live: vi.fn(),
	fetchObjectDetail: vi.fn()
}));
vi.mock('$lib/fetch/extrasolar/lookup', () => ({ extrasolarLookup: { live } }));
vi.mock('$lib/fetch/objects/object-data', () => ({ fetchObjectDetail }));

// The page's planet files: the α Cen system and its index.
vi.mock('$lib/fetch/extrasolar/planets', async (importOriginal) => {
	const actual = await importOriginal<typeof import('$lib/fetch/extrasolar/planets')>();
	const { ALPHA_CEN, INDEX, planet } = await import('$lib/scene/exoplanets/__fixtures__/system');
	const pulsar = {
		token: INDEX.token,
		system: 1091633172,
		hosts: [],
		planets: [planet(1091633172, 1, null), planet(1091633172, 2, null)]
	};
	const files: Record<string, unknown> = {
		'planets/index.json.gz': INDEX,
		'planets/27424668.json.gz': ALPHA_CEN,
		'planets/1091633172.json.gz': pulsar
	};
	const planets = {
		token: INDEX.token,
		index: 'planets/index.json.gz',
		system: 'planets/{key}.json.gz'
	};
	return {
		...actual,
		planetCatalogue: new actual.PlanetCatalogue({
			metadata: async () => ({ planets }) as never,
			json: async <T>(path: string) => files[path] as T,
			allowed: () => true
		})
	};
});

import { extrasolarAlias, fetchPageName, groupPageName, objectPageName } from './page-name';
import { MERGED_HOST } from '$lib/scene/exoplanets/__fixtures__/system';

const pair = (global: string | undefined, localized?: string) => ({
	global: global === undefined ? null : { name: global },
	localized: localized === undefined ? null : { name: localized }
});

describe('objectPageName', () => {
	it('takes the localized name before the catalogue name', () => {
		expect(objectPageName('spkid-20177049', pair('2003 EE16', '(177049) 2003 EE16'), null)).toBe(
			'(177049) 2003 EE16'
		);
		expect(objectPageName('spkid-20177049', pair('2003 EE16'), null)).toBe('2003 EE16');
	});

	it('is empty for an object the export gives no name', () => {
		expect(objectPageName('norad_satcat-1', pair(undefined), null)).toBe('');
	});

	it('names the page of a planetary barycenter after the system of its primary', () => {
		expect(objectPageName('naif-5', pair('Jupiter Barycenter'), pair('Jupiter'))).toBe(
			'Jupiter system'
		);
		expect(objectPageName('naif-3', pair('Earth-Moon Barycenter'), pair('Earth'))).toBe(
			'Earth–Moon system'
		);
	});

	it('keeps the own name of a barycenter whose primary has none', () => {
		expect(objectPageName('naif-5', pair('Jupiter Barycenter'), null)).toBe('Jupiter Barycenter');
	});
});

describe('groupPageName', () => {
	it('takes the name of the localized bundle', () => {
		expect(groupPageName('const-starlink', 'Starlink')).toBe('Starlink');
	});

	it('shows the label of a category, not its bundle name', () => {
		expect(groupPageName('cat-moons', 'Natural satellites')).toBe('Moons');
	});

	it('falls back on the label of the slug', () => {
		expect(groupPageName('class-APO', undefined)).toBe('Apollo');
	});
});

describe('fetchPageName of a star', () => {
	// The alias 9 names the live ID 7.
	const vega = { kind: 'live', record: { id: 7, metadata: { name: 'Vega', object: true } } };

	it('takes the name of the object entry of the live ID', async () => {
		live.mockResolvedValue(vega);
		fetchObjectDetail.mockResolvedValue({ global: null, localized: { name: 'Вега' } });
		expect(await fetchPageName({ kind: 'body', id: 'x-9' })).toBe('Вега');
		expect(fetchObjectDetail).toHaveBeenCalledWith('x-7', true, undefined, true);
	});

	it('takes the Metadata name when the object entry does not load', async () => {
		live.mockResolvedValue(vega);
		fetchObjectDetail.mockRejectedValue(new Error('503'));
		expect(await fetchPageName({ kind: 'body', id: 'x-9' })).toBe('Vega');
	});
});

describe('the name of a planet page', () => {
	it('is the name its system file gives it', async () => {
		expect(await fetchPageName({ kind: 'body', id: 'x-27424668-b-2' })).toBe('Planet 27424668 2');
		expect(await fetchPageName({ kind: 'body', id: 'x-564339647-b-1' })).toBe('Planet 564339647 1');
	});

	it('is the name of the live planet an alias leads to, on any host', async () => {
		expect(await fetchPageName({ kind: 'body', id: 'x-1091633172-b-3' })).toBe(
			'Planet 1091633172 2'
		);
		expect(await fetchPageName({ kind: 'body', id: `x-${MERGED_HOST}-b-1` })).toBe(
			'Planet 27424668 2'
		);
	});

	it('is empty for a planet with no page', async () => {
		expect(await fetchPageName({ kind: 'body', id: 'x-27424668-b-9' })).toBe('');
		expect(await fetchPageName({ kind: 'body', id: 'x-22137869-b-1' })).toBe('');
	});
});

describe('the alias of a planet', () => {
	it('leads to the live planet, on any host', async () => {
		expect(await extrasolarAlias('x-1091633172-b-3')).toEqual({
			id: 'x-1091633172-b-2',
			name: 'Planet 1091633172 2'
		});
		expect(await extrasolarAlias(`x-${MERGED_HOST}-b-1`)).toEqual({
			id: 'x-27424668-b-2',
			name: 'Planet 27424668 2'
		});
	});

	it('is none for a live planet or a number with no page', async () => {
		expect(await extrasolarAlias('x-27424668-b-1')).toBeNull();
		expect(await extrasolarAlias('x-27424668-b-9')).toBeNull();
		expect(await extrasolarAlias(`x-${MERGED_HOST}-b-2`)).toBeNull();
	});
});

describe('the alias of a star', () => {
	const vega = { kind: 'live', record: { id: 7, metadata: { name: 'Vega', object: true } } };

	it('leads to the live ID, named as its page is', async () => {
		live.mockResolvedValue(vega);
		fetchObjectDetail.mockResolvedValue({ global: null, localized: { name: 'Вега' } });
		expect(await extrasolarAlias('x-9')).toEqual({ id: 'x-7', name: 'Вега' });
		fetchObjectDetail.mockRejectedValue(new Error('503'));
		expect(await extrasolarAlias('x-9')).toEqual({ id: 'x-7', name: 'Vega' });
	});

	// The opening view waits on this: a live page must not wait on its bundle.
	it('is none for a live ID, and does not fetch its object entry', async () => {
		live.mockResolvedValue(vega);
		fetchObjectDetail.mockClear();
		expect(await extrasolarAlias('x-7')).toBeNull();
		expect(fetchObjectDetail).not.toHaveBeenCalled();
	});

	it('is none for an ID with no page', async () => {
		live.mockResolvedValue({ kind: 'missing', reason: 'no-row' });
		expect(await extrasolarAlias('x-9')).toBeNull();
	});
});
