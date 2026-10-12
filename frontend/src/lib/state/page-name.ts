/**
 * The name a page of the catalogue goes by: its title, and the name segment
 * of its URL. The server and the page share these rules, so the canonical
 * link of a page is the URL the page writes.
 */

import * as m from '$lib/paraglide/messages.js';
import { dominantPlanetId } from '$lib/constants';
import { fetchGroupDetail } from '$lib/fetch/groups/details';
import { CATEGORY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import { fetchBodyNomenclature } from '$lib/fetch/nomenclature/fetch';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { categoryLabel } from '$lib/format/group';
import { groupSlugLabel } from './focusable';

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
	const planetId = dominantPlanetId(subject.id);
	const [own, primary] = await Promise.all([
		fetchObjectDetail(subject.id, subject.localized),
		planetId ? fetchObjectDetail(planetId) : null
	]);
	return objectPageName(subject.id, own, primary);
}
