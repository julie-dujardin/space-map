import type { SatelliteCategory } from '$lib/fetch/groups/registry';
import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';

// OpsStatus enum values from data/.../constants/earth_sats/satcat.py
const OPS_STATUS_NAME: Record<string, () => string> = {
	operational: m.ops_status_operational,
	nonoperational: m.ops_status_nonoperational,
	partial: m.ops_status_partial,
	backup: m.ops_status_backup,
	spare: m.ops_status_spare,
	extended_mission: m.ops_status_extended,
	decayed: m.ops_status_decayed
};

export function formatOpsStatus(value: string): string {
	return OPS_STATUS_NAME[value]?.() ?? m.unknown();
}

// SatcatObjectType enum values
const OBJECT_TYPE_NAME: Record<string, () => string> = {
	payload: m.object_type_payload,
	rocket_body: m.object_type_rocket_body,
	debris: m.object_type_debris
};

export function formatObjectType(value: string): string {
	return OBJECT_TYPE_NAME[value]?.() ?? m.unknown();
}

/** Object-chip wording, longer than the `satellite_category_*` group-badge
 *  namespace. Keyed on the whole union so a new member cannot fall through to
 *  the raw slug. */
const CATEGORY_NAME: Record<SatelliteCategory, () => string> = {
	communications: m.category_communications,
	navigation: m.category_navigation,
	weather: m.category_weather,
	observation: m.category_observation,
	science: m.category_science,
	military: m.category_military,
	'disaster-sar': m.category_disaster_sar,
	debris: m.category_debris,
	station: m.category_station,
	manned_capsule: m.category_manned_capsule,
	unmanned_cargo: m.category_unmanned_cargo,
	space_tug: m.category_space_tug,
	rocket: m.category_rocket,
	upper_stage: m.category_upper_stage,
	miscellaneous: m.category_miscellaneous
};

/** The slug comes straight from the export, so an unknown one is possible. */
export function formatCategory(slug: string): string {
	return CATEGORY_NAME[slug as SatelliteCategory]?.() ?? slug;
}

/** States that no longer exist, which the browser resolves to their successor:
 *  `SU` comes back as Russia and `CS` as Serbia. GCAT files a launch under the
 *  state that registered it, so the whole point of those two codes is that they
 *  are *not* the successor. */
const HISTORICAL_COUNTRY: Record<string, () => string> = {
	SU: () => m.country_su(),
	CS: () => m.country_cs()
};

export function formatCountry(code: string): string {
	const upper = code.toUpperCase();
	const historical = HISTORICAL_COUNTRY[upper];
	if (historical) return historical();
	try {
		const dn = new Intl.DisplayNames([getLocale()], { type: 'region' });
		return dn.of(upper) ?? code;
	} catch {
		return code;
	}
}

// Formerly-assigned ISO 3166-1 codes that don't have emoji flags.
const NO_FLAG = new Set(['SU', 'AN', 'CS', 'YU', 'DD', 'BU', 'ZR', 'TP']);

// Regional-indicator unicode flag for ISO 3166-1 alpha-2 code.
export function countryFlag(code: string): string {
	if (code.length !== 2) return '';
	const upper = code.toUpperCase();
	if (NO_FLAG.has(upper)) return '';
	const base = 0x1f1e6 - 'A'.charCodeAt(0);
	return String.fromCodePoint(upper.charCodeAt(0) + base, upper.charCodeAt(1) + base);
}
