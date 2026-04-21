import { describe, it, expect, vi } from 'vitest';

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string | undefined>) =>
		route
			.replace('[type]', params.type ?? '')
			.replace('[id]', params.id ?? '')
			.replace('/[[name]]', params.name ? `/${params.name}` : '')
}));

// `parseUrl` reads `$app/state.page` reactively. We don't exercise it here —
// these tests cover `serializeUrl`, which is pure-ish (only depends on `resolve`).
vi.mock('$app/state', () => ({ page: { params: {}, url: new URL('http://x/') } }));

import { serializeUrl } from './url';
import type { MapViewState } from './view';

const baseView: MapViewState = {
	type: 'body',
	id: 'naif-10',
	name: 'Sun',
	date: new Date('2026-01-15T12:00:00Z'),
	isNow: false,
	latitude: 45,
	longitude: 0,
	zoom: 42.43,
	imageIndex: null
};

describe('serializeUrl', () => {
	it('drops the name segment when name is empty', () => {
		expect(serializeUrl({ ...baseView, name: '' })).toBe(
			'/body/10?at=2026-01-15T12:00:00.000Z,45.00000,0.00000,42.430'
		);
	});

	it('writes "now" instead of an ISO date when isNow is true', () => {
		const url = serializeUrl({ ...baseView, isNow: true });
		expect(url).toContain('?at=now,');
	});

	it('uses the spkid- URL prefix for small bodies', () => {
		const url = serializeUrl({ ...baseView, type: 'sb', id: 'spkid-20134340', name: 'Bennu' });
		expect(url.startsWith('/sb/20134340/Bennu?at=')).toBe(true);
	});

	it('uses the norad_satcat- URL prefix for satellites', () => {
		const url = serializeUrl({ ...baseView, type: 'sat', id: 'norad_satcat-25544', name: 'ISS' });
		expect(url.startsWith('/sat/25544/ISS?at=')).toBe(true);
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
});
