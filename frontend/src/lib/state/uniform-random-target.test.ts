/**
 * Every catalogued thing gets one ticket: the object bundles, the feature
 * bundles and the collection index, weighted by how many entries each holds.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { CAT_SOLAR_SYSTEM, CAT_SURFACE_FEATURES } from '$lib/fetch/groups/registry';
import type { GroupDetailData } from '$lib/fetch/groups/details';
import { uniformRandomTarget } from './uniform-random-target';

/** Round counts, so a ticket value names the pool it falls in: objects hold
 *  8 of the 12 tickets, the landforms 1, the three collection pages 3. */
const INDEX = {
	[CAT_SOLAR_SYSTEM]: { n: 8 },
	[CAT_SURFACE_FEATURES]: { n: 1 },
	'const-starlink': { n: 12221 }
};
const OBJECTS = 0.5;
const FEATURES = 0.7;
const COLLECTIONS = 0.9;

let indexFails = false;
vi.mock('$lib/fetch/groups/registry', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/fetch/groups/registry')>()),
	fetchGroupIndex: () =>
		indexFails ? Promise.reject(new Error('offline')) : Promise.resolve(INDEX)
}));

vi.mock('$lib/fetch/metadata', () => ({
	fetchMetadata: () =>
		Promise.resolve({ object_bundles: { global: 4 }, feature_bundles: { global: 2 } })
}));

vi.mock('$lib/fetch/data-base', () => ({ versionedUrl: (path: string) => path }));

const fetched: string[] = [];
vi.mock('$lib/fetch/bundle-cache', () => ({
	fetchGzipBundle: (url: string) => {
		fetched.push(url);
		return Promise.resolve(
			url.includes('nomenclature')
				? { 'naif-499:12': {}, 'naif-499:34': {} }
				: { 'spkid-1': { name: '2013 UR4' }, 'naif-599': { name: 'Jupiter' } }
		);
	}
}));

vi.mock('$lib/fetch/groups/details', () => ({
	fetchGroupDetail: (slug: string) =>
		Promise.resolve({
			localized: { name: slug === 'const-starlink' ? 'Starlink' : slug }
		} as GroupDetailData)
}));

vi.mock('$lib/fetch/nomenclature/fetch', () => ({
	fetchBodyNomenclature: () => Promise.resolve([{ featureId: 34, name: 'Adivar' }])
}));

/** Successive draws over the unit interval, so a test names the branch it takes. */
function draws(...values: number[]) {
	let i = 0;
	vi.spyOn(Math, 'random').mockImplementation(() => values[Math.min(i++, values.length - 1)]);
}

afterEach(() => {
	vi.restoreAllMocks();
	fetched.length = 0;
	indexFails = false;
});

describe('uniformRandomTarget', () => {
	it('draws an object out of a random detail bundle', async () => {
		draws(OBJECTS, 0.75, 0.9);
		await expect(uniformRandomTarget()).resolves.toEqual({
			kind: 'object',
			id: 'naif-599',
			name: 'Jupiter'
		});
		expect(fetched).toEqual(['/v1/objects/__global__/3.json.gz']);
	});

	it('names a landform from its body label file, the bundle having none', async () => {
		draws(FEATURES, 0.5, 0.9);
		await expect(uniformRandomTarget()).resolves.toEqual({
			kind: 'feature',
			bodyId: 'naif-499',
			featureId: 34,
			name: 'Adivar'
		});
	});

	it('routes a landform the labels never named', async () => {
		// Feature 12 is missing from the label file; the name segment is decoration.
		draws(FEATURES, 0.5, 0);
		await expect(uniformRandomTarget()).resolves.toMatchObject({ featureId: 12, name: '' });
	});

	it('draws a collection page off the index, no bundle at all', async () => {
		draws(COLLECTIONS, 0.9);
		await expect(uniformRandomTarget()).resolves.toEqual({
			kind: 'group',
			slug: 'const-starlink',
			name: 'Starlink'
		});
		expect(fetched).toEqual([]);
	});

	it('weighs each pool by what it holds, not by what it is', async () => {
		// The last ticket that is still an object, and the first that is not.
		draws(8 / 12 - 1e-9, 0, 0);
		await expect(uniformRandomTarget()).resolves.toMatchObject({ kind: 'object' });
		draws(8 / 12, 0, 0);
		await expect(uniformRandomTarget()).resolves.toMatchObject({ kind: 'feature' });
	});

	it('keeps no memory of what it drew', async () => {
		const getItem = vi.fn(() => null);
		vi.stubGlobal('localStorage', { getItem, setItem: vi.fn() });
		draws(OBJECTS, 0.75, 0.9);
		await uniformRandomTarget();
		expect(getItem).not.toHaveBeenCalled();
	});

	it('gives up rather than guessing when the index is unreachable', async () => {
		indexFails = true;
		vi.spyOn(console, 'warn').mockImplementation(() => {});
		await expect(uniformRandomTarget()).resolves.toBeNull();
	});
});
