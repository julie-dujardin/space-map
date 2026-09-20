/**
 * Ready-made comparisons. A set drawn on one scale only says something when
 * its members are within reach of each other, so these are the sets worth
 * opening the page on: a family, at a size a single row can hold.
 */

import * as m from '$lib/paraglide/messages.js';
import { ObjectType, type BodyData } from '$lib/types/objects';

export interface ComparePreset {
	slug: string;
	label: () => string;
	/** Object ids, in no particular order: the row sorts by size. */
	ids: string[];
	/** The kinds of object this set is the natural comparison for: one of them,
	 *  on its own page, is offered this set to join. Absent where the members
	 *  stand for nothing but themselves. */
	kinds?: ObjectType[];
	/** Where one kind spans more than a single scale can hold, the half this
	 *  set is. Radii in kilometres, `min` inclusive and `max` exclusive. */
	minRadiusKm?: number;
	maxRadiusKm?: number;
	/** Narrows a kind the ids tell apart but the type does not — an orbiting
	 *  station and an interstellar probe are both spacecraft. */
	idPrefixes?: string[];
}

/** Everything the small-body row holds: the bodies measured in tens of
 *  kilometres rather than thousands. */
const SMALL_BODY_KINDS = [
	ObjectType.DWARF_PLANET,
	ObjectType.ASTEROID,
	ObjectType.ASTEROID_INNER,
	ObjectType.ASTEROID_MAIN_BELT,
	ObjectType.ASTEROID_TROJAN,
	ObjectType.ASTEROID_CENTAUR,
	ObjectType.ASTEROID_TNO,
	ObjectType.COMET
];

/** Where the planets split: Uranus is the smallest giant, Earth the largest
 *  of the others, and no scale carries both ends. */
const GIANT_RADIUS_KM = 20000;

export const COMPARE_PRESETS: ComparePreset[] = [
	{
		slug: 'terrestrial-planets',
		label: m.compare_preset_terrestrial,
		ids: ['naif-199', 'naif-299', 'naif-399', 'naif-499', 'naif-301'],
		kinds: [ObjectType.PLANET],
		maxRadiusKm: GIANT_RADIUS_KM
	},
	{
		slug: 'giant-planets',
		label: m.compare_preset_giants,
		ids: ['naif-599', 'naif-699', 'naif-799', 'naif-899'],
		kinds: [ObjectType.PLANET],
		minRadiusKm: GIANT_RADIUS_KM
	},
	{
		slug: 'galilean-moons',
		label: m.compare_preset_galilean,
		ids: ['naif-501', 'naif-502', 'naif-503', 'naif-504']
	},
	{
		slug: 'large-moons',
		label: m.compare_preset_large_moons,
		ids: ['naif-503', 'naif-606', 'naif-504', 'naif-501', 'naif-301', 'naif-502', 'naif-701'],
		kinds: [ObjectType.MOON]
	},
	{
		slug: 'visited-small-bodies',
		label: m.compare_preset_small_bodies,
		ids: [
			'naif-2000001',
			'spkid-20000004',
			'spkid-20000253',
			'spkid-20000433',
			'spkid-20000243',
			'spkid-20000951',
			'spkid-1000012',
			'spkid-20162173',
			'spkid-20101955',
			'spkid-20025143'
		],
		kinds: SMALL_BODY_KINDS
	},
	{
		slug: 'space-stations',
		label: m.compare_preset_stations,
		ids: ['norad_satcat-25544', 'norad_satcat-16609', 'norad_satcat-6633'],
		kinds: [ObjectType.SPACECRAFT],
		idPrefixes: ['norad_satcat-']
	},
	{
		slug: 'observatories',
		label: m.compare_preset_observatories,
		ids: ['norad_satcat-20580', 'norad_satcat-25867', 'norad_satcat-21225', 'probe-115347456']
	},
	{
		slug: 'outer-probes',
		label: m.compare_preset_probes,
		ids: [
			'probe-49065984',
			'probe-49000448',
			'probe-88592384',
			'probe-104804352',
			'probe-107159552'
		],
		kinds: [ObjectType.SPACECRAFT],
		idPrefixes: ['probe-']
	}
];

/** What the page opens on: a set that fills more than one band, so the way
 *  pages work is visible without the reader having to assemble one. */
export const DEFAULT_PRESET = 'visited-small-bodies';

/** Whether a preset is up: every one of its members is in the comparison. A
 *  set assembled one object at a time reads as the preset it amounts to. */
export function presetOn(preset: ComparePreset, selected: readonly string[]): boolean {
	return preset.ids.every((id) => selected.includes(id));
}

export function presetBySlug(slug: string): ComparePreset | undefined {
	return COMPARE_PRESETS.find((p) => p.slug === slug);
}

/** Whether a body is one of the things this set stands for. */
function fits(preset: ComparePreset, body: BodyData): boolean {
	if (!preset.kinds?.includes(body.objectType)) return false;
	if (preset.idPrefixes && !preset.idPrefixes.some((p) => body.id.startsWith(p))) return false;
	if (preset.minRadiusKm !== undefined && body.radiusKm < preset.minRadiusKm) return false;
	if (preset.maxRadiusKm !== undefined && body.radiusKm >= preset.maxRadiusKm) return false;
	return true;
}

/** The comparison a body's own page offers: the set it already belongs to,
 *  else the set its kind belongs in with the body added to it. Null where the
 *  page has nothing to hold the body up against. */
export function compareSeed(body: BodyData): string[] | null {
	const member = COMPARE_PRESETS.find((p) => p.ids.includes(body.id));
	if (member) return member.ids;
	const kin = COMPARE_PRESETS.find((p) => fits(p, body));
	return kin ? [body.id, ...kin.ids] : null;
}
