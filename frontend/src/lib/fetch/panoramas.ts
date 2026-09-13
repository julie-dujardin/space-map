/**
 * Which traverses have panorama coverage, from `/data/v1/panoramas.json`.
 *
 * The index carries no ground points: a body's bundle already holds every
 * entry, so the gallery reads the summary to know which bodies to fetch and
 * takes the traverses from there.
 */

import { dataBase } from './data-base';
import { fetchWithTimeout } from './fetch-timeout';

/** One probe's coverage on a body, as `export/panoramas.py` writes it. */
export interface PanoramaMissionSummary {
	mission: string;
	/** `probe-<id>` of the craft that drove this traverse; absent where the
	 *  spacecraft table does not describe it. */
	probe?: string;
	count: number;
	first_time: string;
	last_time: string;
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
