import { DEFAULT_SKY_CULTURE } from '$lib/constants';
import { cultureName, type SkyCultureEntry } from '$lib/fetch/extrasolar/skycultures';
import { foldForSearch } from '$lib/format/fold';
import { SKY_CULTURE_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import * as m from '$lib/paraglide/messages.js';
import type { AppState } from '$lib/state/app-state.svelte';
import type { getSettings } from '$lib/state/settings.svelte';
import { pageSkyOf } from '$lib/state/url';
import { UrlType } from '$lib/state/view';

/** The picker's region groups in their order: the keys of
 *  ``SKY_CULTURE_REGIONS`` in ``data/constants/stars/cultures.py``. */
export const SKY_REGIONS: readonly (readonly [string, () => string])[] = [
	['modern', m.sky_region_modern],
	['northern-africa', m.sky_region_northern_africa],
	['southern-africa', m.sky_region_southern_africa],
	['northern-america', m.sky_region_northern_america],
	['central-america', m.sky_region_central_america],
	['south-america', m.sky_region_south_america],
	['eastern-asia', m.sky_region_eastern_asia],
	['northern-asia', m.sky_region_northern_asia],
	['south-eastern-asia', m.sky_region_south_eastern_asia],
	['southern-asia', m.sky_region_southern_asia],
	['western-asia', m.sky_region_western_asia],
	['eastern-europe', m.sky_region_eastern_europe],
	['northern-europe', m.sky_region_northern_europe],
	['southern-europe', m.sky_region_southern_europe],
	['western-europe', m.sky_region_western_europe],
	['australasia', m.sky_region_australasia],
	['melanesia', m.sky_region_melanesia],
	['polynesia', m.sky_region_polynesia]
];

const REGION_LABELS = new Map(SKY_REGIONS);

export function regionLabel(group: string | null): string {
	return (group && REGION_LABELS.get(group)?.()) ?? '';
}

/** A pick opens the culture in the sidebar. The trip planner stays: a group
 *  ends the trip, so there a pick only changes the setting. */
export function pickCulture(
	culture: SkyCultureEntry,
	locale: string,
	settings: Pick<
		ReturnType<typeof getSettings>,
		'setConstellationCulture' | 'setShowConstellations' | 'setPageSky'
	>,
	appState: Pick<AppState, 'view' | 'setGroup'>
): void {
	settings.setConstellationCulture(culture.key);
	settings.setShowConstellations(true);
	if (appState.view.type === UrlType.Nav) return;
	const slug = `${SKY_CULTURE_SLUG_PREFIX}${culture.key}`;
	// Set here too: a pick of the page in view changes no group, and its sky can be hidden.
	settings.setPageSky(pageSkyOf(slug, false));
	appState.setGroup(slug, cultureName(culture, locale));
}

export type SkyCultureOrder = 'region' | 'name' | 'figures';

/** Rows in the order the menu asks for. */
export function orderCultures(
	cultures: readonly SkyCultureEntry[],
	order: Exclude<SkyCultureOrder, 'region'>,
	locale: string
): SkyCultureEntry[] {
	const collator = new Intl.Collator(locale);
	const byName = (a: SkyCultureEntry, b: SkyCultureEntry) =>
		collator.compare(cultureName(a, locale), cultureName(b, locale));
	return [...cultures].sort(
		order === 'name' ? byName : (a, b) => b.figures - a.figures || byName(a, b)
	);
}

/** The regions that have cultures, in their order, each by name with the
 *  default first. */
export function byRegion(
	cultures: readonly SkyCultureEntry[],
	locale: string
): { group: string; label: string; cultures: SkyCultureEntry[] }[] {
	const named = orderCultures(cultures, 'name', locale).sort(
		(a, b) => Number(b.key === DEFAULT_SKY_CULTURE) - Number(a.key === DEFAULT_SKY_CULTURE)
	);
	return SKY_REGIONS.flatMap(([group, label]) => {
		const inside = named.filter((culture) => culture.group === group);
		return inside.length > 0 ? [{ group, label: label(), cultures: inside }] : [];
	});
}

/** A reader may type the culture in their language, in English, or its region. */
export function matchCulture(culture: SkyCultureEntry, query: string, locale: string): boolean {
	const needle = foldForSearch(query);
	return [cultureName(culture, locale), culture.name, regionLabel(culture.group)].some((text) =>
		foldForSearch(text).includes(needle)
	);
}
