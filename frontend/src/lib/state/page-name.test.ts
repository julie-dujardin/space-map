import { describe, expect, it, vi } from 'vitest';
import { fetchPageName, groupPageName, objectPageName } from './page-name';

const { live, fetchObjectDetail } = vi.hoisted(() => ({
	live: vi.fn(),
	fetchObjectDetail: vi.fn()
}));
vi.mock('$lib/fetch/extrasolar/lookup', () => ({ extrasolarLookup: { live } }));
vi.mock('$lib/fetch/objects/object-data', () => ({ fetchObjectDetail }));

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
