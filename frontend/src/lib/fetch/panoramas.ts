/**
 * What panorama coverage exists: which traverses, from
 * `/data/v1/panoramas.json`, and the ground points themselves, from the
 * body's own bundle.
 *
 * The index carries no ground points on purpose — a body's bundle already
 * holds every entry — so a reader picking a body takes the summary and one
 * picking a place takes the list.
 */

import { dataBase } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';
import { fetchObjectDetail, type PanoramaEntry } from './objects/object-data';

/** One probe's coverage on a body, as `export/panoramas.py` writes it. */
export interface PanoramaMissionSummary {
	mission: string;
	/** `probe-<id>` of the craft that drove this traverse; absent where the
	 *  spacecraft table does not describe it. */
	probe?: string;
	count: number;
	first_time: string;
	last_time: string;
	/** False where no stop on the traverse publishes a sphere: the places are
	 *  on the map, and there is nothing to open. */
	imagery?: boolean;
}

export interface PanoramaBodySummary {
	id: string;
	missions: PanoramaMissionSummary[];
}

/** `fetcher` takes the `fetch` a SvelteKit `load` is handed, so the request
 *  joins the page's own load rather than starting a second one. */
export async function fetchPanoramaIndex(
	fetcher: (url: string) => Promise<Response> = fetchWithTimeout
): Promise<PanoramaBodySummary[]> {
	const res = await fetcher(`${dataBase()}/v1/panoramas.json`);
	if (!res.ok) throw new Error(`Failed to load panoramas.json: ${res.status}`);
	const index = (await res.json()) as { bodies?: PanoramaBodySummary[] };
	return index.bodies ?? [];
}

/** Every panorama taken on a body, mission by mission in time order. The view
 *  reads the same list when it opens; a page that decides which panorama to
 *  open reads it first. Empty when the body has none. */
export async function fetchPanoramas(bodyId: string): Promise<PanoramaEntry[]> {
	const detail = await fetchObjectDetail(bodyId, false);
	return detail.global?.panoramas ?? [];
}
