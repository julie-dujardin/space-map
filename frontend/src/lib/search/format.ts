import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import { classNameFromSlug, orbitClassLabel } from '$lib/charts/orbit-zones';
import { CATEGORY_SLUG_PREFIX } from '$lib/fetch/groups/registry';
import { featureTypeLabel } from '$lib/format/feature-type';
import { categoryLabel, groupNameMessage } from '$lib/format/group';
import {
	localizedDescription,
	localizedName,
	planetHostName,
	type GroupHit,
	type SearchHit
} from '$lib/search/client';

const messages = m as unknown as Record<
	string,
	((args?: Record<string, unknown>) => string) | undefined
>;

/** YYYYMMDD int → calendar year (negative = BCE). */
export function inceptionYear(yyyymmdd: number): number {
	return Math.trunc(yyyymmdd / 10000);
}

/** DOM id for a result row, shared by the option elements and the combobox
 *  input's aria-activedescendant. */
export function optionDomId(hitId: string): string {
	return `search-option-${hitId}`;
}

/** Upper-case the first character only, for filter labels (the `type_*` keys are
 *  sentence-case for inline use — "moon of Saturn" — so we capitalize at display
 *  rather than mutate them). No-op on already-capitalized or non-Latin text. */
export function capitalize(s: string): string {
	return s ? s[0].toLocaleUpperCase(getLocale()) + s.slice(1) : s;
}

/** Everything the Sun holds directly: naming that parent says nothing. */
const HELIOCENTRIC_TYPES = new Set(['planet', 'dwarf_planet', 'comet', 'asteroid']);
const SELF_EXPLANATORY_TYPES = new Set(['star', 'spacecraft', 'undocumented']);

/** A class as a type key: "brown dwarf" is `brown_dwarf`. */
function slug(cls: string | null): string {
	return (cls ?? 'planet').replace(/[ -]/g, '_');
}

/** Localized object type, sentence-case for inline use ("moon of Saturn"). */
export function typeLabel(type: string): string {
	const key = type.startsWith('asteroid') ? 'type_asteroid' : `type_${type}`;
	return messages[key]?.() ?? type.replace(/_/g, ' ');
}

/** A collection's name in the reader's locale. Categories, orbit classes and
 *  feature types have messages of their own; the other kinds have a
 *  `group_name_<slug>` message, else the exported name. */
export function groupName(g: GroupHit, locale: string): string {
	if (g.slug.startsWith(CATEGORY_SLUG_PREFIX)) return categoryLabel(g.slug);
	const className = classNameFromSlug(g.slug);
	if (className != null) {
		const label = orbitClassLabel(className);
		if (label !== className) return label;
		const idx = localizedName(g, locale);
		return idx && idx !== g.slug ? idx : className;
	}
	const featureType = featureTypeLabel(g.slug);
	if (featureType) return featureType;
	return groupNameMessage(g.slug) ?? localizedName(g, locale);
}

/** The name on a result row. */
export function hitName(hit: SearchHit, locale: string): string {
	return hit.kind === 'group' ? groupName(hit, locale) : localizedName(hit, locale);
}

/** Names a hit's second line needs but cannot carry: parents and hosts arrive
 *  as ids, feature types as IAU codes. Each caller resolves them from what it
 *  already has loaded. */
export interface HitLabelResolvers {
	bodyName: (bodyId: string) => string;
	featureTypeLabel: (code: string) => string;
}

/** What a hit says of its star system: the system of a star, the stars of a
 *  system. */
function systemFact(hit: SearchHit): string | null {
	if (hit.kind !== 'object') return null;
	const type = typeLabel(hit.type);
	if (hit.system_name) return m.search_secondary_in_system({ type, system: hit.system_name });
	if (hit.star_count === undefined) return null;
	const stars = m.search_secondary_system({
		type,
		stars: m.system_star_count({ count: hit.star_count })
	});
	return hit.planet_count
		? `${stars} · ${m.exoplanet_planet_count({ count: hit.planet_count })}`
		: stars;
}

/** The line under a result's name: its own description when it has one, else
 *  what it is and what it belongs to. A star system's facts lead the line. */
export function secondaryText(hit: SearchHit, resolve: HitLabelResolvers): string {
	// Its description only calls a satellite system a barycenter.
	if (hit.kind === 'object' && hit.moon_count !== undefined) {
		return m.moons_count_moon({ count: hit.moon_count });
	}
	const desc = localizedDescription(hit, getLocale());
	const fact = systemFact(hit);
	if (desc) return fact ? `${fact} · ${desc}` : desc;
	if (fact) return fact;
	if (hit.kind === 'feature') {
		return m.search_secondary_feature_on({
			type: resolve.featureTypeLabel(hit.feature_type),
			parent: resolve.bodyName(hit.body_id)
		});
	}
	if (hit.kind === 'group') return '';
	// A pad says where it is; its own name is only ever a complex number.
	if (hit.kind === 'pad') return hit.site_name;
	// A planet of another system names its star, a star of one its planets.
	if (hit.kind === 'planet') {
		return m.search_secondary_orbiting({
			type: typeLabel(slug(hit.class)),
			parent: planetHostName(hit, getLocale())
		});
	}
	if (hit.planet_count) {
		return m.search_secondary_planet_host({
			type: typeLabel(hit.type),
			planets: m.exoplanet_planet_count({ count: hit.planet_count })
		});
	}
	if (hit.id.startsWith('norad_satcat-')) {
		return hit.type === 'debris' ? m.type_earth_debris() : m.type_earth_satellite();
	}
	const label = typeLabel(hit.type);
	if (HELIOCENTRIC_TYPES.has(hit.type) || SELF_EXPLANATORY_TYPES.has(hit.type)) return label;
	if (hit.parent_id) {
		return m.search_secondary_orbiting({ type: label, parent: resolve.bodyName(hit.parent_id) });
	}
	return label;
}
