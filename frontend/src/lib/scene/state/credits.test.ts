import { afterEach, describe, expect, it } from 'vitest';
import { configureHost } from '$lib/host';
import { CreditsStore } from './credits.svelte';

const map = { source: 'https://example.org/map', organisation: 'USGS' };
const mosaic = { source: 'https://example.org/mosaic', organisation: 'NASA' };

describe('CreditsStore.registerImagery', () => {
	afterEach(() => configureHost({}));

	it('credits a surface map and the other work in its tile pyramid', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org' });
		const credits = new CreditsStore();
		credits.registerImagery('surface', 'naif-499', 'naif-4', { ...map, tiles: mosaic });
		const organisations = credits.imageryOf('surface').map((credit) => credit.organisation);
		expect(organisations).toEqual(['USGS', 'NASA']);
	});

	it('credits the map alone where the host draws no tiles', () => {
		const credits = new CreditsStore();
		credits.registerImagery('surface', 'naif-499', 'naif-4', { ...map, tiles: mosaic });
		expect(credits.imageryOf('surface')).toHaveLength(1);
	});

	it('leaves out the pyramid of a height map, which is not drawn', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org' });
		const credits = new CreditsStore();
		credits.registerImagery('topography', 'naif-499', 'naif-4', { ...map, tiles: mosaic });
		expect(credits.imageryOf('topography')).toHaveLength(1);
	});

	it('keeps the first surface map a body registers', () => {
		const credits = new CreditsStore();
		credits.registerImagery('surface', 'naif-499', 'naif-4', map);
		credits.registerImagery('surface', 'naif-499', 'naif-4', mosaic);
		expect(credits.imageryOf('surface').map((credit) => credit.source)).toEqual([map.source]);
	});

	it('keeps every work of a ring bundle', () => {
		const credits = new CreditsStore();
		credits.registerImagery('rings', 'naif-699', 'naif-6', map);
		credits.registerImagery('rings', 'naif-699', 'naif-6', mosaic);
		expect(credits.imageryOf('rings')).toHaveLength(2);
	});
});
