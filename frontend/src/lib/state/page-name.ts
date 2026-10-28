/**
 * The name a page of the catalogue goes by: its title, and the name segment
 * of its URL. The server and the page share these rules, so the canonical
 * link of a page is the URL the page writes. The sitemap must list that same
 * URL: `export/sitemap.py` in the data package mirrors the rules.
 */

import * as m from '$lib/paraglide/messages.js';
import { dominantPlanetId } from '$lib/constants';
import { fetchGroupDetail } from '$lib/fetch/groups/details';
import { CATEGORY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { categoryLabel } from '$lib/format/group';
import { groupSlugLabel } from './focusable';
import {
	EXTRASOLAR_PREFIX,
	extrasolarObjectId,
	isStarObjectId,
	planetObjectId,
	planetOfObjectId
} from '$lib/fetch/extrasolar/ids';
import { extrasolarLookup, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { planetCatalogue, type Planet } from '$lib/fetch/extrasolar/planets';

/** The Earth–Moon barycenter and Earth itself. */
const EARTH_MOON_IDS = new Set(['naif-3', 'naif-399']);

/** "<primary> system" — except Earth's, which nobody calls the Earth system. */
export function systemTitle(id: string, primary: string): string {
	return EARTH_MOON_IDS.has(id)
		? m.planetary_system_title_earth_moon()
		: m.planetary_system_title({ primary });
}

/** An object's bundles, as far as its name goes. */
interface NamedPair {
	global: { name?: string } | null;
	localized: { name?: string } | null;
}

function bundleName(pair: NamedPair | null): string {
	return pair?.localized?.name || pair?.global?.name || '';
}

/**
 * The name of an object's page, from its own bundles and those of `primary`:
 * the planet, when `id` is a planetary barycenter. That page is the one of the
 * whole system, named off its primary.
 */
export function objectPageName(id: string, own: NamedPair, primary: NamedPair | null): string {
	const planetId = dominantPlanetId(id);
	const primaryName = bundleName(primary);
	return planetId && primaryName ? systemTitle(planetId, primaryName) : bundleName(own);
}

/** A collection's name, given the one its localized bundle holds. Categories
 *  display an i18n label, not the English bundle name. */
export function groupPageName(slug: string, bundleName: string | undefined): string {
	return slug.startsWith(CATEGORY_SLUG_PREFIX)
		? categoryLabel(slug)
		: (bundleName ?? groupSlugLabel(slug));
}

/** What a page is about. */
export type PageSubject =
	| {
			kind: 'body';
			id: string;
			/** False for a body known to have no localized entry: its bundle is
			 *  not fetched. */
			localized?: boolean;
	  }
	| { kind: 'feature'; bodyId: string; featureId: number }
	| { kind: 'group'; slug: string };

/** A star's name: the one of its object entry in the reader's language, else
 *  the one of its Metadata row. */
async function starPageName(record: ExtrasolarRecord): Promise<string> {
	const meta = record.metadata;
	const own = await fetchObjectDetail(
		extrasolarObjectId(record.id),
		meta.object,
		undefined,
		true
	).catch(() => null);
	return own?.localized?.name ?? meta.name ?? '';
}

/** A planet's name: the one of its object entry in the reader's language, else
 *  the one of its system file. */
async function planetPageName(planet: Planet): Promise<string> {
	if (!planet.object) return planet.name;
	const own = await fetchObjectDetail(
		planetObjectId(planet.host, planet.number),
		true,
		undefined,
		true
	).catch(() => null);
	return own?.localized?.name ?? planet.name;
}

/**
 * The live object an alias of the extrasolar catalogue leads to, and the name
 * of its page: a star's live ID, or a planet's live number, maybe on another
 * host. Null when `id` is live, when it has no page, or when a file does not
 * load. A live ID gets no name: the opening view waits on this, and a star's
 * name needs its object bundle.
 */
export async function extrasolarAlias(id: string): Promise<{ id: string; name: string } | null> {
	const planet = planetOfObjectId(id);
	if (planet) {
		const live = await planetCatalogue.planet(planet.host, planet.n).catch(() => null);
		if (!live) return null;
		const liveId = planetObjectId(live.planet.host, live.planet.number);
		return liveId === id ? null : { id: liveId, name: await planetPageName(live.planet) };
	}
	const found = await extrasolarLookup.live(id.slice(EXTRASOLAR_PREFIX.length)).catch(() => null);
	if (found?.kind !== 'live') return null;
	const liveId = extrasolarObjectId(found.record.id);
	return liveId === id ? null : { id: liveId, name: await starPageName(found.record) };
}

/** The name of a page, read from the export in the reader's language. Empty
 *  when the export gives none. */
export async function fetchPageName(subject: PageSubject): Promise<string> {
	if (subject.kind === 'group') {
		return groupPageName(subject.slug, (await fetchGroupDetail(subject.slug)).localized?.name);
	}
	if (subject.kind === 'feature') {
		const features = await fetchBodyNomenclature(subject.bodyId);
		return features.find((f) => f.featureId === subject.featureId)?.name ?? '';
	}
	// A planet is named by its object entry, else by its system file. A star is
	// named by the object entry of its live ID, else by its Metadata row.
	const planet = planetOfObjectId(subject.id);
	if (planet) {
		const found = await planetCatalogue.planet(planet.host, planet.n);
		return found ? planetPageName(found.planet) : '';
	}
	if (isStarObjectId(subject.id)) {
		const found = await extrasolarLookup.live(subject.id.slice(EXTRASOLAR_PREFIX.length));
		return found.kind === 'live' ? starPageName(found.record) : '';
	}
	const planetId = dominantPlanetId(subject.id);
	// In the background: at boot these bundles would take the link from the
	// scene's own fetches, and nothing waits on a name.
	const [own, primary] = await Promise.all([
		fetchObjectDetail(subject.id, subject.localized, undefined, true),
		planetId ? fetchObjectDetail(planetId, true, undefined, true) : null
	]);
	return objectPageName(subject.id, own, primary);
}
