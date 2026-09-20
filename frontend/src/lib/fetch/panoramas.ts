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

/** The index is one static file that several pages want — the gallery, a
 *  world's own gallery, the drawer's traverse tab — so the first read is the
 *  one everybody gets. Dropped on failure, so a retry is a real retry. */
let index: Promise<PanoramaBodySummary[]> | null = null;

/** `fetcher` takes the `fetch` a SvelteKit `load` is handed, so the request
 *  joins the page's own load rather than starting a second one. */
export function fetchPanoramaIndex(
	fetcher: (url: string) => Promise<Response> = fetchWithTimeout
): Promise<PanoramaBodySummary[]> {
	if (index) return index;
	index = (async () => {
		const res = await fetcher(`${dataBase()}/v1/panoramas.json`);
		if (!res.ok) throw new Error(`Failed to load panoramas.json: ${res.status}`);
		const body = (await res.json()) as { bodies?: PanoramaBodySummary[] };
		return body.bodies ?? [];
	})();
	index.catch(() => (index = null));
	return index;
}

/** Every panorama taken on a body, mission by mission in time order. The view
 *  reads the same list when it opens; a page that decides which panorama to
 *  open reads it first. Empty when the body has none. */
export async function fetchPanoramas(bodyId: string): Promise<PanoramaEntry[]> {
	const detail = await fetchObjectDetail(bodyId, false);
	return detail.global?.panoramas ?? [];
}
