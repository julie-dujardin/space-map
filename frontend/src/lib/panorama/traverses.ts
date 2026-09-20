/** A body's panorama coverage as the galleries draw it: one traverse per craft,
 *  carrying only the stops a reader can open. */

import { fetchObjectDetail, type PanoramaEntry } from '$lib/fetch/objects/object-data';
import { fetchPanoramaIndex, type PanoramaBodySummary } from '$lib/fetch/panoramas';
import * as m from '$lib/paraglide/messages.js';
import { capitalize } from '$lib/search/format';

export interface Traverse {
	mission: string;
	/** The craft's own name where the spacecraft table describes it, else the
	 *  slug the pipeline minted. */
	name: string;
	/** In the order the bundle publishes them, which is time order. */
	entries: PanoramaEntry[];
}

/**
 * The traverses of one body, from the stops a reader can open — callers filter
 * with `isViewable`, since the lists they hold are filtered already. `summary`
 * is the body's row in the panorama index, which says which whole traverses
 * publish no spheres; without it every mission counts, the index being the only
 * thing that would say otherwise. `name` resolves the craft behind a mission.
 */
export function traversesOf(
	entries: readonly PanoramaEntry[],
	summary: PanoramaBodySummary | undefined,
	name: (mission: string) => string | undefined
): Traverse[] {
	const withheld = new Set(
		(summary?.missions ?? []).filter((mm) => mm.imagery === false).map((mm) => mm.mission)
	);
	const byMission = new Map<string, PanoramaEntry[]>();
	for (const entry of entries) {
		const mission = entry.mission ?? '';
		if (withheld.has(mission)) continue;
		let list = byMission.get(mission);
		if (!list) byMission.set(mission, (list = []));
		list.push(entry);
	}
	return [...byMission].map(([mission, found]) => ({
		mission,
		name: name(mission) ?? capitalize(mission),
		entries: found
	}));
}

/** The craft behind each of a body's traverses, by mission — the index points
 *  at their pages, and the name is the page's. */
export async function traverseCrewNames(
	summary: PanoramaBodySummary | undefined
): Promise<Map<string, string>> {
	const pairs = await Promise.all(
		(summary?.missions ?? [])
			.filter((mm) => !!mm.probe)
			.map(async (mm) => {
				const detail = await fetchObjectDetail(mm.probe as string).catch(() => null);
				return [mm.mission, detail?.localized?.name ?? detail?.global?.name] as const;
			})
	);
	return new Map(pairs.filter((p): p is readonly [string, string] => !!p[1]));
}

/** Held per body: the gallery is walked into and back out of as panoramas open
 *  and close, and the index and the craft pages behind it do not change while
 *  the page is up. */
const byBody = new Map<string, Promise<Traverse[]>>();

/** One body's traverses, named, for a page that is about that body alone. */
export function bodyTraverses(
	bodyId: string,
	entries: readonly PanoramaEntry[]
): Promise<Traverse[]> {
	const held = byBody.get(bodyId);
	if (held) return held;
	const found = (async () => {
		const summary = await fetchPanoramaIndex()
			.then((bodies) => bodies.find((b) => b.id === bodyId))
			.catch(() => undefined);
		const names = await traverseCrewNames(summary);
		return traversesOf(entries, summary, (mission) => names.get(mission));
	})();
	byBody.set(bodyId, found);
	return found;
}

/** The years a traverse spans, or the one year it sits in. */
export function traverseYears(entries: readonly { time: string }[]): string {
	const start = new Date(entries[0].time).getUTCFullYear();
	const end = new Date(entries[entries.length - 1].time).getUTCFullYear();
	return start === end
		? String(start)
		: m.panorama_gallery_years({ start: String(start), end: String(end) });
}
