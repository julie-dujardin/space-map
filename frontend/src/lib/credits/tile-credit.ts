import { tilesBase } from '$lib/fetch/data-base';
import { textureAllowed } from '$lib/host';
import type { CreditFields } from './imagery-layers';

/**
 * The credit of a map's tile pyramid, where this host draws tiles and the
 * pyramid holds another work than the map. Both are then on screen: the map
 * from afar, the tiles up close.
 */
export function tileCredit(map: CreditFields & { tiles?: CreditFields }): CreditFields | undefined {
	const tiles = map.tiles;
	if (!tiles || tilesBase() === '' || !textureAllowed(tiles.distribution)) return undefined;
	const same = tiles.source === map.source && tiles.attribution === map.attribution;
	return same ? undefined : tiles;
}
