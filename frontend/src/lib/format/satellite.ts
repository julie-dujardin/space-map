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

export function formatCountry(code: string): string {
	try {
		const dn = new Intl.DisplayNames([getLocale()], { type: 'region' });
		return dn.of(code.toUpperCase()) ?? code;
	} catch {
		return code;
	}
}

// Regional-indicator unicode flag for ISO 3166-1 alpha-2 code.
export function countryFlag(code: string): string {
	if (code.length !== 2) return '';
	const base = 0x1f1e6 - 'A'.charCodeAt(0);
	const upper = code.toUpperCase();
	return String.fromCodePoint(upper.charCodeAt(0) + base, upper.charCodeAt(1) + base);
}
