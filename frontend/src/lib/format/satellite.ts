import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';

// OpsStatus enum values from data/.../constants/earth_sats/satcat.py
export function formatOpsStatus(value: string): string {
	switch (value) {
		case 'operational':
			return m.ops_status_operational();
		case 'nonoperational':
			return m.ops_status_nonoperational();
		case 'partial':
			return m.ops_status_partial();
		case 'backup':
			return m.ops_status_backup();
		case 'spare':
			return m.ops_status_spare();
		case 'extended_mission':
			return m.ops_status_extended();
		case 'decayed':
			return m.ops_status_decayed();
		default:
			return m.unknown();
	}
}

// SatcatObjectType enum values
export function formatObjectType(value: string): string {
	switch (value) {
		case 'payload':
			return m.object_type_payload();
		case 'rocket_body':
			return m.object_type_rocket_body();
		case 'debris':
			return m.object_type_debris();
		default:
			return m.unknown();
	}
}

// SatelliteCategory enum values from data/.../constants/earth_sats/constellations.py
export function formatCategory(slug: string): string {
	switch (slug) {
		case 'communications':
			return m.category_communications();
		case 'navigation':
			return m.category_navigation();
		case 'weather':
			return m.category_weather();
		case 'observation':
			return m.category_observation();
		case 'science':
			return m.category_science();
		case 'military':
			return m.category_military();
		case 'disaster-sar':
			return m.category_disaster_sar();
		case 'debris':
			return m.category_debris();
		case 'station':
			return m.category_station();
		case 'miscellaneous':
			return m.category_miscellaneous();
		default:
			return slug;
	}
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
