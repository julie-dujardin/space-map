/**
 * The services the site asks at run time, and whether each one answers. A
 * probe is a request from the browser of the reader, so it also fails where
 * the network of the reader cannot reach the service.
 */

import { env } from '$env/dynamic/public';
import type { AboutData } from '$lib/about/data-payload';
import { dataBase, tileRoot, tilesBase } from '$lib/fetch/data-base';
import { host } from '$lib/host';
import * as m from '$lib/paraglide/messages.js';

export interface Backend {
	id: string;
	label: () => string;
	/** The address that the next probe asks. */
	url: () => string | Promise<string>;
}

/** The services of this deployment. Search and tiles are absent where the
 *  deployment turns them off. */
export function backends(): Backend[] {
	const out: Backend[] = [];
	const search = env.PUBLIC_MEILI_URL?.replace(/\/$/, '');
	if (search) {
		out.push({ id: 'search', label: m.status_service_search, url: () => `${search}/health` });
	}
	out.push({
		id: 'live',
		label: m.status_service_live,
		url: () => `${host().liveUrl}/v1/activity.json`
	});
	if (tilesBase()) {
		out.push({
			id: 'tiles',
			label: m.status_service_tiles,
			// The edge cache keeps tiles. A query of its own takes each probe
			// past the edge to the server.
			url: async () => `${await firstTile()}?probe=${Date.now()}`
		});
	}
	return out;
}

/** The first tile of a pyramid that the export names. The tile host serves
 *  tiles and nothing else, so it has no health route. */
async function firstTile(): Promise<string> {
	const res = await fetch(`${dataBase()}/v1/about-data.json`);
	const data = (await res.json()) as AboutData;
	const maps = data.systems.flatMap((system) => system.worlds.flatMap((world) => world.maps));
	// A map of more than one frame keeps its pyramids one folder down.
	const map = maps.find((candidate) => candidate.tiles && !candidate.frames);
	if (!map) throw new Error('The export names no tile pyramid');
	return `${tileRoot(map)}0/0/0.webp`;
}

const PROBE_TIMEOUT_MS = 10_000;

/** True when the service answers with a success. A stored answer says nothing
 *  about now, so the probe does not read the cache. */
export async function probe(backend: Backend): Promise<boolean> {
	try {
		const res = await fetch(await backend.url(), {
			cache: 'no-store',
			signal: AbortSignal.timeout(PROBE_TIMEOUT_MS)
		});
		void res.body?.cancel();
		return res.ok;
	} catch {
		return false;
	}
}
