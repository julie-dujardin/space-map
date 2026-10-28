import { describe, expect, it, vi } from 'vitest';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

import { env } from '$env/dynamic/public';
import { isExtrasolarHit, searchEndpoints, toHit } from './client';
import { secondaryText } from './format';

/** The search documents of the extrasolar export, as the index stores them. */
const PLANET = {
	id: 'x-27424668-b-1',
	kind: 'planet',
	name: 'Proxima Cen b',
	planet: {
		host_id: 'x-27424668',
		number: 1,
		system_id: 'x-27424668',
		host_name: 'Proxima Centauri',
		designation: 'Proxima Cen b',
		class: 'planet',
		status: 'confirmed',
		aliases: ['Proxima b'],
		discovery_year: 2016,
		discovery_method: 'Radial Velocity'
	}
};
const HOST = {
	id: 'x-27424668',
	kind: 'object',
	name: 'Proxima Centauri',
	object: { id: 'x-27424668', type: 'star', extrasolar: true, planets: 3 }
};
const resolve = { bodyName: (id: string) => id, featureTypeLabel: (code: string) => code };

describe('extrasolar search hits', () => {
	it('lifts a planet out of its document, keyed by its scene id', () => {
		const hit = toHit(PLANET);
		expect(hit).toMatchObject({
			kind: 'planet',
			id: 'x-27424668-b-1',
			name: 'Proxima Cen b',
			host_id: 'x-27424668',
			number: 1,
			host_name: 'Proxima Centauri',
			class: 'planet'
		});
		expect(secondaryText(hit, resolve)).toBe('planet of Proxima Centauri');
		const dwarf = toHit({ ...PLANET, planet: { ...PLANET.planet, class: 'brown dwarf' } });
		expect(secondaryText(dwarf, resolve)).toBe('brown dwarf of Proxima Centauri');
	});

	it('reads a host as an object of the catalogue, with its planets', () => {
		const hit = toHit(HOST);
		expect(hit).toMatchObject({ kind: 'object', id: 'x-27424668', extrasolar: true, planets: 3 });
		expect(secondaryText(hit, resolve)).toBe('star with 3 planets');
		const pulsar = toHit({ ...HOST, object: { ...HOST.object, type: 'pulsar', planets: 1 } });
		expect(secondaryText(pulsar, resolve)).toBe('pulsar with 1 planet');
	});

	it('tells the stars and planets of other systems from the rest', () => {
		expect(isExtrasolarHit(toHit(PLANET))).toBe(true);
		expect(isExtrasolarHit(toHit(HOST))).toBe(true);
		const sun = toHit({
			id: 'naif-10',
			kind: 'object',
			name: 'Sun',
			object: { id: 'naif-10', type: 'star' }
		});
		expect(isExtrasolarHit(sun)).toBe(false);
	});
});

describe('endpoint search', () => {
	it('leaves out every extrasolar class before the result limit, but the Sun', async () => {
		const search = vi.fn().mockResolvedValue({ hits: [] });
		Object.assign(env, {
			PUBLIC_MEILI_URL: 'https://search.example',
			PUBLIC_MEILI_SEARCH_KEY: 'test-key'
		});
		vi.doMock('meilisearch', () => ({
			Meilisearch: class {
				index() {
					return { search };
				}
			}
		}));

		await searchEndpoints('PSR', 'en', 5);

		expect(search).toHaveBeenLastCalledWith('PSR', {
			limit: 5,
			locales: ['en'],
			filter:
				'kind != "group" AND kind != "planet" AND ' +
				'(object.type NOT IN ["star", "pulsar", "white_dwarf", "brown_dwarf", "binary_star", "multiple_star"] OR object.id = "naif-10")'
		});
	});
});
