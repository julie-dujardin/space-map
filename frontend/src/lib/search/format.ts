import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import { localizedDescription, type SearchHit } from '$lib/search/client';

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
const HELIOCENTRIC_TYPES = new Set([
	'planet',
	'dwarf_planet',
	'comet',
	'asteroid',
	'asteroid_inner',
	'asteroid_main_belt',
	'asteroid_trojan',
	'asteroid_centaur',
	'asteroid_tno'
]);
const SELF_EXPLANATORY_TYPES = new Set(['star', 'spacecraft', 'undocumented']);

/** Localized object type, sentence-case for inline use ("moon of Saturn"). */
export function typeLabel(type: string): string {
	const key = type.startsWith('asteroid') ? 'type_asteroid' : `type_${type}`;
	return messages[key]?.() ?? type.replace(/_/g, ' ');
}

/** Names a hit's second line needs but cannot carry: parents and hosts arrive
 *  as ids, feature types as IAU codes. Each caller resolves them from what it
 *  already has loaded. */
export interface HitLabelResolvers {
	bodyName: (bodyId: string) => string;
	featureTypeLabel: (code: string) => string;
}

/** The line under a result's name: its own description when it has one, else
 *  what it is and what it belongs to. */
export function secondaryText(hit: SearchHit, resolve: HitLabelResolvers): string {
	const desc = localizedDescription(hit, getLocale());
	if (desc) return desc;
	if (hit.kind === 'feature') {
		return m.search_secondary_feature_on({
			type: resolve.featureTypeLabel(hit.feature_type),
			parent: resolve.bodyName(hit.body_id)
		});
	}
	if (hit.kind === 'group') return '';
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
