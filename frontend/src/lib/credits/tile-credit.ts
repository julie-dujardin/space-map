import { tilesBase } from '$lib/fetch/data-base';
import { textureAllowed } from '$lib/host';
import type { CreditFields } from './imagery-layers';

/** A surface map with the credit of its tile pyramid and of the pyramid's patches. */
export type TiledMap = CreditFields & {
	tiles?: CreditFields & { patches?: CreditFields[] };
};

/**
 * The credit of a map's tile pyramid, where this host draws tiles and the
 * pyramid holds another work than the map. Both are then on screen: the map
 * from afar, the tiles up close.
 */
export function tileCredit(map: TiledMap): CreditFields | undefined {
	const tiles = map.tiles;
	if (!tiles || tilesBase() === '' || !textureAllowed(tiles.distribution)) return undefined;
	const same = tiles.source === map.source && tiles.attribution === map.attribution;
	return same ? undefined : tiles;
}

/**
 * The credits of the patches of a map's tile pyramid, where this host draws
 * tiles: each is a regional mosaic of its own, on screen over its own ground.
 * Mosaics of one source are credited once.
 */
export function patchCredits(map: TiledMap): CreditFields[] {
	const tiles = map.tiles;
	if (!tiles?.patches || tilesBase() === '' || !textureAllowed(tiles.distribution)) return [];
	const bySource = new Map(tiles.patches.map((patch) => [patch.source, patch]));
	return [...bySource.values()];
}
