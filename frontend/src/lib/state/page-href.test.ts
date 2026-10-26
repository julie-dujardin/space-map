import { describe, expect, it, vi } from 'vitest';

vi.mock('$app/paths', () => ({
	resolve: (route: string, params: Record<string, string | undefined>) =>
		route
			.replace('[type]', params.type ?? '')
			.replace('[id]', params.id ?? '')
			.replace('[n]', params.n ?? '')
			.replace('[featureId]', params.featureId ?? '')
			.replace('/[[name]]', params.name ? `/${params.name}` : '')
}));

import { bodyHref, planetHref, searchHitHref } from './page-href';
import { toHit } from '$lib/search/client';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

describe('the page of a planet', () => {
	it('is /x/<host>/b/<n>/<name>', () => {
		expect(planetHref(27424668, 1, 'Proxima Cen b')).toBe('/x/27424668/b/1/Proxima%20Cen%20b');
		expect(planetHref(27424668, 1, '')).toBe('/x/27424668/b/1');
	});

	it('is where a body link to a planet goes, labels and search hits included', () => {
		expect(bodyHref('x-27424668-b-1', 'Proxima Cen b')).toBe('/x/27424668/b/1/Proxima%20Cen%20b');
		expect(bodyHref('x-27424668', 'Proxima Centauri')).toBe('/x/27424668/Proxima%20Centauri');
		const hit = toHit({
			id: 'x-20657986-b-1',
			kind: 'planet',
			name: 'Kepler-16 b',
			planet: { host_id: 'x-20657986', number: 1 }
		});
		expect(searchHitHref(hit, 'Kepler-16 b')).toBe('/x/20657986/b/1/Kepler-16%20b');
	});
});
