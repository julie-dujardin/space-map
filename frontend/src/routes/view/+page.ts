/**
 * `/view` — every traverse that has panorama coverage, one card per probe.
 *
 * Client-rendered: the loader fetches `/data`, which collides with the
 * `[type]/[id]` route under SSR (same reason as the credits page).
 */

import { fetchObjectDetail, type PanoramaEntry } from '$lib/fetch/objects/object-data';
import { fetchPanoramaIndex } from '$lib/fetch/panoramas';
import { meanRadiusKm } from '$lib/fetch/objects/physical';
import type { PageLoad } from './$types';

export const ssr = false;

/** One probe's panoramas on one body, in traverse order. */
export interface Traverse {
	mission: string;
	entries: PanoramaEntry[];
}

/** A body and the traverses recorded on it. */
export interface CoveredBody {
	id: string;
	name: string;
	/** Mean radius, kilometres; sizes each map's scale bar. */
	radiusKm: number;
	traverses: Traverse[];
}

export const load: PageLoad = async ({ fetch }) => {
	const summaries = await fetchPanoramaIndex(fetch).catch(() => null);
	if (!summaries) return { bodies: [], failed: true };

	const details = await Promise.all(
		summaries.map((summary) => fetchObjectDetail(summary.id).catch(() => null))
	);
	const bodies: CoveredBody[] = [];
	for (const detail of details) {
		const global = detail?.global;
		if (!global?.panoramas?.length) continue;
		const byMission = new Map<string, PanoramaEntry[]>();
		for (const entry of global.panoramas)
			byMission.set(entry.mission ?? '', [...(byMission.get(entry.mission ?? '') ?? []), entry]);
		bodies.push({
			id: global.id,
			name: detail?.localized?.name ?? global.name ?? global.id,
			radiusKm: meanRadiusKm(global) ?? 0,
			traverses: [...byMission].map(([mission, entries]) => ({ mission, entries }))
		});
	}
	// A body that answered with no panoramas is data moving on; nothing
	// answering at all is a failure worth saying out loud.
	return { bodies, failed: bodies.length === 0 && summaries.length > 0 };
};
