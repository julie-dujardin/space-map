/**
 * `/view` — every traverse that has panorama coverage, one card per probe.
 *
 * Client-rendered: the loader fetches `/data`, which collides with the
 * `[type]/[id]` route under SSR (same reason as the credits page).
 */

import { fetchObjectDetail, isViewable } from '$lib/fetch/objects/object-data';
import { traverseCrewNames, traversesOf, type Traverse } from '$lib/panorama/traverses';
import { fetchPanoramaIndex } from '$lib/fetch/panoramas';
import { meanRadiusKm } from '$lib/fetch/objects/physical';
import type { PageLoad } from './$types';

export const ssr = false;

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

/** What the gallery draws, once the index and every body behind it answer. */
export interface GalleryData {
	bodies: CoveredBody[];
	summary: GallerySummary;
	/** The index answered with coverage, but nothing behind it did. */
	failed: boolean;
}

/**
 * The gallery as assembled this session.
 *
 * Assembling it reads the detail bundle of every world and every craft on the
 * index — 25 buckets, against a bundle LRU that holds 24 — so the LRU cannot
 * hold the working set and every pass re-downloads and re-parses all of it.
 * Held the same way one body's traverses are, and for the same reason: the
 * gallery is walked into and back out of, and the index does not change while
 * the page is up.
 */
let held: Promise<GalleryData> | null = null;

// The gallery is handed over unresolved: the page draws its frame the moment
// the row is clicked and fills in when the index and the bodies land.
export const load: PageLoad = ({ fetch }) => ({ gallery: gallery(fetch) });

function gallery(fetch: typeof globalThis.fetch): Promise<GalleryData> {
	if (held) return held;
	const pending = buildGallery(fetch);
	held = pending;
	// A pass that found nothing is a blip to retry, not an answer to keep.
	void pending.then(
		(data) => {
			if (held === pending && data.bodies.length === 0) held = null;
		},
		() => {
			if (held === pending) held = null;
		}
	);
	return pending;
}

async function buildGallery(fetch: typeof globalThis.fetch): Promise<GalleryData> {
	const summaries = await fetchPanoramaIndex(fetch).catch(() => null);
	if (!summaries)
		return { bodies: [], summary: { panoramas: 0, probes: 0, worlds: 0 }, failed: true };

	// The craft that drove each traverse, so a card can borrow its name. Keyed
	// the way traverses are grouped — by body and mission both, since a slug is
	// only unique within the body it was recorded on.
	const probes = new Map<string, string>();
	for (const body of summaries)
		for (const summary of body.missions)
			if (summary.imagery !== false && summary.probe)
				probes.set(`${body.id}/${summary.mission}`, summary.probe);
	// A traverse published as places only has no sphere for a card to open, so
	// an index with none of them is coverage nobody can reach.
	const anyViewable = summaries.some((body) => body.missions.some((mm) => mm.imagery !== false));
	// Bodies and the craft on them, all at once: one waits on the other only
	// through the index, which is already in hand.
	const [details, crews] = await Promise.all([
		Promise.all(summaries.map((body) => fetchObjectDetail(body.id).catch(() => null))),
		Promise.all(summaries.map((body) => traverseCrewNames(body)))
	]);
	const bodies: CoveredBody[] = [];
	// A craft counts once however many bodies or traverses carry it; a traverse
	// with no probe on record stands for itself.
	const counted = new Set<string>();
	let panoramas = 0;
	for (const [i, detail] of details.entries()) {
		const global = detail?.global;
		if (!global) continue;
		const crew = crews[i];
		const traverses = traversesOf(
			(global.panoramas ?? []).filter(isViewable),
			summaries[i],
			(mission) => crew.get(mission)
		);
		if (!traverses.length) continue;
		for (const traverse of traverses) {
			const key = `${global.id}/${traverse.mission}`;
			counted.add(probes.get(key) ?? key);
			panoramas += traverse.entries.length;
		}
		bodies.push({
			id: global.id,
			name: detail?.localized?.name ?? global.name ?? global.id,
			radiusKm: meanRadiusKm(global) ?? 0,
			traverses
		});
	}
	// A body that answered with no panoramas is data moving on; nothing
	// answering at all is a failure worth saying out loud.
	const summary: GallerySummary = {
		panoramas,
		probes: counted.size,
		worlds: bodies.length
	};
	return { bodies, summary, failed: bodies.length === 0 && anyViewable };
}
