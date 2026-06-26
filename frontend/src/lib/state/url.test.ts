import { describe, it, expect, vi } from 'vitest';

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string | undefined>) =>
		route
			.replace('[type]', params.type ?? '')
			.replace('[id]', params.id ?? '')
			.replace('[featureId]', params.featureId ?? '')
			.replace('/[[name]]', params.name ? `/${params.name}` : '')
}));

// `parseUrl` reads `$app/state.page` reactively. We don't exercise it here —
// these tests cover `serializeUrl`, which is pure-ish (only depends on `resolve`).
vi.mock('$app/state', () => ({ page: { params: {}, url: new URL('http://x/') } }));

import { serializeUrl } from './url';
import type { MapViewState } from './view';

const baseView: MapViewState = {
	type: 'b',
	id: 'naif-10',
	name: 'Sun',
	date: new Date('2026-01-15T12:00:00Z'),
	isNow: false,
	latitude: 45,
	longitude: 0,
	zoom: 42.43,
	imageIndex: null,
	featureId: null,
	groupSlug: null,
	tab: null,
	memberPage: null
};

describe('serializeUrl', () => {
	it('drops the name segment when name is empty', () => {
		expect(serializeUrl({ ...baseView, name: '' })).toBe(
			'/b/10?at=2026-01-15T12:00:00.000Z,45.00000,0.00000,42.430'
		);
	});

	it('writes "now" instead of an ISO date when isNow is true', () => {
		const url = serializeUrl({ ...baseView, isNow: true });
		expect(url).toContain('?at=now,');
	});

	it('uses the spkid- URL prefix for small bodies', () => {
		const url = serializeUrl({ ...baseView, type: 's', id: 'spkid-20134340', name: 'Bennu' });
		expect(url.startsWith('/s/20134340/Bennu?at=')).toBe(true);
	});

	it('uses the norad_satcat- URL prefix for satellites', () => {
		const url = serializeUrl({ ...baseView, type: 'e', id: 'norad_satcat-25544', name: 'ISS' });
		expect(url.startsWith('/e/25544/ISS?at=')).toBe(true);
	});

	it('nests features under the body route with the body type segment', () => {
		const url = serializeUrl({
			...baseView,
			type: 'f',
			id: 'naif-301',
			featureId: 14940,
			name: 'Tycho'
		});
		expect(url.startsWith('/b/301/f/14940/Tycho?at=')).toBe(true);
	});

	it('uses the s/ type segment for features on small bodies', () => {
		const url = serializeUrl({
			...baseView,
			type: 'f',
			id: 'spkid-20000004',
			featureId: 14940,
			name: 'Licinia'
		});
		expect(url.startsWith('/s/20000004/f/14940/Licinia?at=')).toBe(true);
	});

	describe('imageIndex serialization', () => {
		it('omits img= when imageIndex is null', () => {
			expect(serializeUrl({ ...baseView, imageIndex: null })).not.toContain('img=');
		});

		it('emits img=0 when imageIndex is 0', () => {
			expect(serializeUrl({ ...baseView, imageIndex: 0 })).toContain('&img=0');
		});

		it('emits img=N for any non-negative integer', () => {
			expect(serializeUrl({ ...baseView, imageIndex: 7 })).toContain('&img=7');
		});

		// Regression: an earlier `state.imageIndex !== null` check let undefined
		// slip through and produced literal "&img=undefined" in the URL.
		it('omits img= when imageIndex is undefined', () => {
			const view = { ...baseView, imageIndex: undefined as unknown as null };
			expect(serializeUrl(view)).not.toContain('img=');
		});

		it('omits img= when imageIndex is NaN', () => {
			const view = { ...baseView, imageIndex: NaN as unknown as number };
			expect(serializeUrl(view)).not.toContain('img=');
		});

		it('omits img= when imageIndex is a non-integer number', () => {
			const view = { ...baseView, imageIndex: 1.5 };
			expect(serializeUrl(view)).not.toContain('img=');
		});
	});

	describe('tab serialization', () => {
		it('omits tab= for the default overview tab (null)', () => {
			expect(serializeUrl({ ...baseView, tab: null })).not.toContain('tab=');
		});

		it('emits &tab=members for the members tab', () => {
			expect(serializeUrl({ ...baseView, tab: 'members' })).toContain('&tab=members');
		});

		it('emits &tab=images for the images tab', () => {
			expect(serializeUrl({ ...baseView, tab: 'images' })).toContain('&tab=images');
		});

		it('serializes the tab on group routes too', () => {
			const url = serializeUrl({
				...baseView,
				type: 'g',
				groupSlug: 'cat-moons',
				name: 'Moons',
				tab: 'members'
			});
			expect(url.startsWith('/g/cat-moons/Moons?at=')).toBe(true);
			expect(url).toContain('&tab=members');
		});
	});

	describe('member-page (mp) serialization', () => {
		it('emits &mp=N under the members tab', () => {
			const url = serializeUrl({ ...baseView, tab: 'members', memberPage: 3 });
			expect(url).toContain('&mp=3');
		});

		it('omits mp= for page 1 (the implicit default)', () => {
			expect(serializeUrl({ ...baseView, tab: 'members', memberPage: 1 })).not.toContain('mp=');
		});

		it('omits mp= when memberPage is null', () => {
			expect(serializeUrl({ ...baseView, tab: 'members', memberPage: null })).not.toContain('mp=');
		});

		// mp is meaningless outside the one paginated list — never leak it onto
		// other tabs even if the field is stale.
		it('omits mp= when the active tab is not members', () => {
			expect(serializeUrl({ ...baseView, tab: 'images', memberPage: 5 })).not.toContain('mp=');
		});
	});
});
