/**
 * `/nav` — the Δv subway map: what it costs to get from one body to the
 * others, as stops on a line. `?from=<id>` moves the origin off Earth,
 * `?hide=<id,id,…>` is what the reader has switched off, and `?to=<id,…>`
 * adds destinations beyond the default set.
 *
 * Client-rendered: the loader fetches `/data`, which collides with the
 * `[type]/[id]` route under SSR (same reason as the credits page). The planner
 * for one trip lives under `/nav/<from>/<to>`; a bare `/nav` is this page.
 */

import { error } from '@sveltejs/kit';
import { EARTH_ID } from '$lib/constants';
import { buildSubwayMap, type SubwayMap } from '$lib/math/travel/subway';
import { isBodyId } from '$lib/state/nav-end';
import {
	defaultSubwayTargets,
	fetchSubwayCatalogue,
	groupBySystem,
	sortByDistance,
	type SubwaySystem
} from '$lib/travel/subway-bodies';
import type { PageLoad } from './$types';

export const ssr = false;

export interface SubwayPageData {
	map: SubwayMap;
	/** Display names and map tints, keyed by body id, for every body a stop can belong to. */
	names: Record<string, string>;
	colors: Record<string, string>;
	/** Every body the drawer offers, grouped by satellite system, in distance
	 *  order and without the origin. */
	systems: SubwaySystem[];
	/** The bodies drawn, in distance order. */
	visible: string[];
	/** The bodies the reader switched off. Distinct from what is not drawn: the
	 *  origin is never drawn as a destination but was not switched off. */
	hidden: string[];
	/** Destinations a link asked for beyond the default set. */
	extra: string[];
	/** Nothing to draw: the catalogue did not answer, or has no orbit for the origin. */
	failed: boolean;
}

/** Ids out of the query, dropping anything that is not one. */
function bodyIds(raw: string | null): string[] | null {
	if (raw === null) return null;
	return raw.split(',').filter(isBodyId);
}

export const load: PageLoad = async ({ url }): Promise<SubwayPageData> => {
	const from = url.searchParams.get('from') ?? EARTH_ID;
	if (!isBodyId(from)) error(404, `Unknown body id "${from}"`);
	const extra = bodyIds(url.searchParams.get('to')) ?? [];
	const hidden = bodyIds(url.searchParams.get('hide')) ?? [];
	const offered = await defaultSubwayTargets();
	// The drawer offers the default set whatever is drawn, and anything a link
	// asked for on top; the origin is never a destination.
	const universe = [...new Set([...offered, ...extra])].filter((id) => id !== from);
	const visible = universe.filter((id) => !hidden.includes(id));

	const catalogue = await fetchSubwayCatalogue([from, ...universe]).catch(() => null);
	if (!catalogue) {
		return {
			map: { originId: from, trunk: [], stations: [], edges: [], routes: [] },
			names: {},
			colors: {},
			systems: [],
			visible,
			hidden,
			extra,
			failed: true
		};
	}
	const ordered = sortByDistance(catalogue.bodies, visible);
	const map = buildSubwayMap(catalogue.bodies, from, ordered);
	return {
		map,
		names: Object.fromEntries(catalogue.names),
		colors: Object.fromEntries(catalogue.colors),
		systems: groupBySystem(catalogue.bodies, universe),
		visible: ordered,
		hidden,
		extra,
		// An origin the catalogue has no orbit for routes nowhere, and so does one
		// whose primary it could not place: the map then has no trunk to draw.
		failed: !catalogue.bodies.has(from) || map.trunk.length === 0
	};
};
