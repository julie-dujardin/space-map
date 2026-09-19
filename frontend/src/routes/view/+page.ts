/**
 * `/view` — every traverse that has panorama coverage, one card per probe.
 *
 * Client-rendered: the loader fetches `/data`, which collides with the
 * `[type]/[id]` route under SSR (same reason as the credits page).
 */

import {
	fetchObjectDetail,
	isViewable,
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

/** How much coverage the gallery holds, for the line under the title. */
export interface GallerySummary {
	panoramas: number;
	probes: number;
	worlds: number;
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
	if (!summaries)
		return { bodies: [], summary: { panoramas: 0, probes: 0, worlds: 0 }, failed: true };

	// The craft that drove each traverse, so a card can borrow its name. Keyed
	// the way traverses are grouped — by body and mission both, since a slug is
	// only unique within the body it was recorded on.
	const probes = new Map<string, string>();
	// A traverse published as places only has no sphere for a card to open.
	const viewable = new Set<string>();
	for (const body of summaries)
		for (const summary of body.missions) {
			if (summary.imagery === false) continue;
			viewable.add(`${body.id}/${summary.mission}`);
			if (summary.probe) probes.set(`${body.id}/${summary.mission}`, summary.probe);
		}
	const [details, named] = await Promise.all([
		Promise.all(summaries.map((summary) => fetchObjectDetail(summary.id).catch(() => null))),
		Promise.all(
			[...probes].map(
				async ([key, probe]) => [key, await fetchObjectDetail(probe).catch(() => null)] as const
			)
		).then((pairs) => new Map(pairs))
	]);
	const bodies: CoveredBody[] = [];
	// A craft counts once however many bodies or traverses carry it; a traverse
	// with no probe on record stands for itself.
	const counted = new Set<string>();
	let panoramas = 0;
	for (const detail of details) {
		const global = detail?.global;
		if (!global?.panoramas?.length) continue;
		const byMission = new Map<string, PanoramaEntry[]>();
		for (const entry of global.panoramas) {
			const mission = entry.mission ?? '';
			// Withholding is per stop as well as per traverse, so a card that
			// counted or opened one would name a sphere the viewer cannot fetch.
			if (!viewable.has(`${global.id}/${mission}`) || !isViewable(entry)) continue;
			byMission.set(mission, [...(byMission.get(mission) ?? []), entry]);
		}
		if (!byMission.size) continue;
		bodies.push({
			id: global.id,
			name: detail?.localized?.name ?? global.name ?? global.id,
			radiusKm: meanRadiusKm(global) ?? 0,
			traverses: [...byMission].map(([mission, entries]) => {
				const key = `${global.id}/${mission}`;
				counted.add(probes.get(key) ?? key);
				panoramas += entries.length;
				return {
					mission,
					name: probeName(named.get(key)) ?? capitalize(mission),
					entries
				};
			})
		});
	}
	// A body that answered with no panoramas is data moving on; nothing
	// answering at all is a failure worth saying out loud.
	const summary: GallerySummary = {
		panoramas,
		probes: counted.size,
		worlds: bodies.length
	};
	return { bodies, summary, failed: bodies.length === 0 && viewable.size > 0 };
};
