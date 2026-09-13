/**
 * `/view` — every traverse that has panorama coverage, one card per probe.
 *
 * Client-rendered: the loader fetches `/data`, which collides with the
 * `[type]/[id]` route under SSR (same reason as the credits page).
 */

import {
	fetchObjectDetail,
	type ObjectDetailData,
	type PanoramaEntry
} from '$lib/fetch/objects/object-data';
import { fetchPanoramaIndex } from '$lib/fetch/panoramas';
import { meanRadiusKm } from '$lib/fetch/objects/physical';
import { capitalize } from '$lib/search/format';
import type { PageLoad } from './$types';

export const ssr = false;

/** One probe's panoramas on one body, in traverse order. */
export interface Traverse {
	mission: string;
	/** What to call the craft: its own localized name where the index names
	 *  a probe, else the slug the pipeline minted. */
	name: string;
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

/** The craft's own name, absent where no probe is on record or its fetch failed. */
function probeName(detail: ObjectDetailData | null | undefined): string | undefined {
	return detail?.localized?.name ?? detail?.global?.name;
}

export const load: PageLoad = async ({ fetch }) => {
	const summaries = await fetchPanoramaIndex(fetch).catch(() => null);
	if (!summaries) return { bodies: [], failed: true };

	// Mission slug -> the craft that drove it, so a card can borrow its name.
	const probes = new Map<string, string>();
	for (const body of summaries)
		for (const summary of body.missions)
			if (summary.probe) probes.set(summary.mission, summary.probe);
	const [details, named] = await Promise.all([
		Promise.all(summaries.map((summary) => fetchObjectDetail(summary.id).catch(() => null))),
		Promise.all(
			[...probes].map(
				async ([mission, probe]) =>
					[mission, await fetchObjectDetail(probe).catch(() => null)] as const
			)
		).then((pairs) => new Map(pairs))
	]);
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
			traverses: [...byMission].map(([mission, entries]) => ({
				mission,
				name: probeName(named.get(mission)) ?? capitalize(mission),
				entries
			}))
		});
	}
	// A body that answered with no panoramas is data moving on; nothing
	// answering at all is a failure worth saying out loud.
	return { bodies, failed: bodies.length === 0 && summaries.length > 0 };
};
