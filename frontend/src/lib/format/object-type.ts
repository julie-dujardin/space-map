import * as m from '$lib/paraglide/messages.js';

// The asteroid zones all collapse to one label: the zone is shown elsewhere.
const TYPE_NAME: Record<string, () => string> = {
	barycenter: m.type_barycenter,
	lagrange_point: m.type_lagrange_point,
	star: m.type_star,
	planet: m.type_planet,
	dwarf_planet: m.type_dwarf_planet,
	moon: m.type_moon,
	asteroid: m.type_asteroid,
	asteroid_inner: m.type_asteroid,
	asteroid_main_belt: m.type_asteroid,
	asteroid_trojan: m.type_asteroid,
	asteroid_centaur: m.type_asteroid,
	asteroid_tno: m.type_asteroid,
	comet: m.type_comet,
	spacecraft: m.type_spacecraft,
	debris: m.type_debris,
	undocumented: m.type_undocumented
};

/** Localized label for an export `global.type` string (lowercase, e.g. "moon"). */
export function objectTypeLabel(type: string): string {
	return TYPE_NAME[type]?.() ?? m.object();
}
