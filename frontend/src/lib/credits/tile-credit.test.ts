import { afterEach, describe, expect, it } from 'vitest';
import { configureHost } from '$lib/host';
import { tileCredit } from './tile-credit';

const map = { source: 'https://example.org/map', organisation: 'USGS', attribution: 'Map' };
const mosaic = { source: 'https://example.org/mosaic', organisation: 'NASA' };

describe('tileCredit', () => {
	afterEach(() => configureHost({}));

	it('is the credit of a pyramid that holds another work than the map', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org' });
		expect(tileCredit({ ...map, tiles: mosaic })).toBe(mosaic);
	});

	it('counts a pyramid from the same source with its own credit line', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org' });
		const detailed = { ...map, attribution: 'Map, detail from a mosaic' };
		expect(tileCredit({ ...map, tiles: detailed })).toBe(detailed);
	});

	it('is nothing for a pyramid of the map itself', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org' });
		expect(tileCredit({ ...map, tiles: { ...map } })).toBeUndefined();
		expect(tileCredit(map)).toBeUndefined();
	});

	it('is nothing where the host draws no tiles', () => {
		configureHost({});
		expect(tileCredit({ ...map, tiles: mosaic })).toBeUndefined();
	});

	it('is nothing for a pyramid this host may not serve', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org', textures: 'open' });
		const held = { ...mosaic, distribution: 'site-only' as const };
		expect(tileCredit({ ...map, tiles: held })).toBeUndefined();
	});
});
