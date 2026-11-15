/** The galaxy that holds the Sun, as the page that the Solar System, a star
 *  system and a lone star climb to. */

import { tilesBase } from '$lib/fetch/data-base';
import { homeGalaxyId } from '$lib/fetch/extrasolar/galaxies';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { getLocale } from '$lib/host';
import type { GalaxyPage } from './breadcrumb';
import { fetchPageName } from './page-name';

let pendingKey: string | null = null;
let pending: Promise<GalaxyPage | null> | null = null;

async function loadHomeGalaxy(): Promise<GalaxyPage | null> {
	const id = await homeGalaxyId();
	if (id === null) return null;
	const name = await fetchPageName({ kind: 'body', id: extrasolarObjectId(id) });
	return name ? { id, name } : null;
}

/**
 * The home galaxy, once per export and language: it is a constant of both.
 * Null where the export names no such galaxy, or its page has no name. A
 * failure is not kept, so the next call tries again.
 */
export function fetchHomeGalaxy(): Promise<GalaxyPage | null> {
	const key = `${getLocale()} ${tilesBase()}`;
	if (pending && pendingKey === key) return pending;
	pendingKey = key;
	const p = loadHomeGalaxy();
	pending = p;
	p.catch(() => {
		if (pending === p) pending = null;
	});
	return p;
}
