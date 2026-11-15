/**
 * The sky of the star charts: the tile pyramid of the star map where a tile
 * host serves it, over the skybox cube. In the drawer the cube is the one that
 * the renderer holds. A chart of the SDK reads the sky of the map it is given,
 * or else the page's own, which loads the cube's tiers only where the export
 * has no pyramid.
 */

import { tilesBase } from '$lib/fetch/data-base';
import { fetchMetadata } from '$lib/fetch/metadata';
import type { CreditsStore } from '$lib/scene/state/credits.svelte';
import { LayeredSky } from '$lib/star-chart/layered-sky';
import type { ChartSky } from '$lib/star-chart/sky';
import { releaseTilePainter, TileSkySource } from '$lib/star-chart/tile-sky';
import { CubeTierSky } from './cube-tier-sky';

export function openChartSky(credits: CreditsStore): LayeredSky {
	return new LayeredSky(async () => {
		if (!tilesBase()) return null;
		const tiles = (await fetchMetadata()).skybox?.tiles;
		if (!tiles) return null;
		// The map names the same work when it loads the cube. It loads none with its stars off.
		credits.skybox ??= {
			source: tiles.source,
			organisation: tiles.organisation,
			license: tiles.license,
			attribution: tiles.attribution
		};
		return new TileSkySource(tiles);
	});
}

interface PageSky {
	sky: LayeredSky;
	cube: CubeTierSky | null;
	/** Charts that read it. */
	holders: number;
	closed: boolean;
}

/** The page's own skies, by the tile host each was made for. */
const pages = new Map<string, PageSky>();
/** Charts that hold a sky, a map's included. All of them paint tiles with one context. */
let holders = 0;

function openPageSky(tiles: string): PageSky {
	const made: PageSky = {
		cube: null,
		holders: 0,
		closed: false,
		sky: new LayeredSky(async () => {
			const skybox = (await fetchMetadata()).skybox;
			if (tiles && skybox?.tiles) return new TileSkySource(skybox.tiles);
			if (!skybox || made.closed) return null;
			try {
				made.cube = new CubeTierSky(skybox);
			} catch (e) {
				// A device with no WebGL 2 stays without one.
				console.warn('[star-chart] no sky from the cube:', e);
				return null;
			}
			made.sky.setCoarse(made.cube);
			return null;
		})
	};
	return made;
}

/**
 * The sky of a chart of the SDK: that of the map whose context is given, or
 * else the page's own for the tile host of the page. `release` lets it go. A
 * page sky closes when its last chart lets go, and the WebGL context of the
 * tiles when the last chart of all does.
 */
export function holdChartSky(map?: { chartSky: ChartSky }): {
	sky: ChartSky;
	release: () => void;
} {
	const tiles = tilesBase();
	let page: PageSky | null = null;
	let sky: ChartSky;
	if (map) sky = map.chartSky;
	else {
		page = pages.get(tiles) ?? openPageSky(tiles);
		pages.set(tiles, page);
		page.holders++;
		sky = page.sky;
	}
	holders++;
	let held = true;
	return {
		sky,
		release: () => {
			if (!held) return;
			held = false;
			if (page && --page.holders === 0) {
				page.closed = true;
				page.sky.setCoarse(null);
				page.cube?.dispose();
				pages.delete(tiles);
			}
			if (--holders === 0) releaseTilePainter();
		}
	};
}
