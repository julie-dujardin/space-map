import { afterEach, describe, expect, it } from 'vitest';
import { configureHost } from '$lib/host';
import type { BodyObjects, TilesBlock } from '$lib/scene/types';
import { tilesServe } from './tile-overlay';

function body(tiles: Partial<TilesBlock> = {}, overlay?: { dead: boolean }): BodyObjects {
	const surfaceTiles = { id: 'naif-499', tile_size: 1024, max_level: 6, version: 'v', ...tiles };
	return { surfaceTiles, tileOverlay: overlay } as unknown as BodyObjects;
}

describe('tilesServe', () => {
	afterEach(() => configureHost({}));

	it('is false where the host names no tile URL, so the tiers load as before', () => {
		configureHost({});
		expect(tilesServe(body())).toBe(false);
	});

	it('is true once the host names one', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org/' });
		expect(tilesServe(body())).toBe(true);
	});

	it('is false for a pyramid that adds no level to the tiers', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org' });
		expect(tilesServe(body({ max_level: 2 }))).toBe(false);
	});

	it('is false after the tile host failed the pyramid', () => {
		configureHost({ tilesUrl: 'https://tiles.example.org' });
		expect(tilesServe(body({}, { dead: true }))).toBe(false);
	});
});
