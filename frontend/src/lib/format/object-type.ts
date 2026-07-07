import * as m from '$lib/paraglide/messages.js';

/** Localized label for an export `global.type` string (lowercase, e.g. "moon"). */
export function objectTypeLabel(type: string): string {
	switch (type) {
		case 'barycenter':
			return m.type_barycenter();
		case 'lagrange_point':
			return m.type_lagrange_point();
		case 'star':
			return m.type_star();
		case 'planet':
			return m.type_planet();
		case 'dwarf_planet':
			return m.type_dwarf_planet();
		case 'moon':
			return m.type_moon();
		case 'asteroid':
		case 'asteroid_inner':
		case 'asteroid_main_belt':
		case 'asteroid_trojan':
		case 'asteroid_centaur':
		case 'asteroid_tno':
			return m.type_asteroid();
		case 'comet':
			return m.type_comet();
		case 'spacecraft':
			return m.type_spacecraft();
		case 'debris':
			return m.type_debris();
		case 'undocumented':
			return m.type_undocumented();
		default:
			return m.object();
	}
}
