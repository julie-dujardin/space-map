/**
 * The sky of the star charts in the drawer: the tile pyramid of the star map
 * where a tile host serves it, over the skybox cube of the renderer.
 */

import { tilesBase } from '$lib/fetch/data-base';
import { fetchMetadata } from '$lib/fetch/metadata';
import type { CreditsStore } from '$lib/scene/state/credits.svelte';
import { LayeredSky } from '$lib/star-chart/layered-sky';
import { TileSkySource } from '$lib/star-chart/tile-sky';

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
