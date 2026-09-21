/**
 * Ready-made comparisons: the sets worth opening the page on. A set only has
 * to be a family — the row pages, so it can run as long as the family does.
 */

import * as m from '$lib/paraglide/messages.js';
import { ObjectType, type BodyData } from '$lib/types/objects';
import { ROCKETS } from './rockets';

export type PresetGroup = 'worlds' | 'craft' | 'probes';

export interface ComparePreset {
	slug: string;
	label: () => string;
	/** The heading it is listed under: bodies, craft near Earth, or craft sent
	 *  away from it. */
	group: PresetGroup;
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
		group: 'worlds',
		label: m.compare_preset_terrestrial,
		ids: ['naif-199', 'naif-299', 'naif-399', 'naif-499'],
		kinds: [ObjectType.PLANET],
		maxRadiusKm: GIANT_RADIUS_KM
	},
	{
		slug: 'giant-planets',
		group: 'worlds',
		label: m.compare_preset_giants,
		ids: ['naif-599', 'naif-699', 'naif-799', 'naif-899'],
		kinds: [ObjectType.PLANET],
		minRadiusKm: GIANT_RADIUS_KM
	},
	{
		// Every moon a scale drew round, down to Mimas: the rest of the
		// hundreds are captured rubble, and belong beside asteroids instead.
		slug: 'large-moons',
		group: 'worlds',
		label: m.compare_preset_large_moons,
		ids: [
			'naif-301',
			'naif-501',
			'naif-502',
			'naif-503',
			'naif-504',
			'naif-601',
			'naif-602',
			'naif-603',
			'naif-604',
			'naif-605',
			'naif-606',
			'naif-608',
			'naif-701',
			'naif-702',
			'naif-703',
			'naif-704',
			'naif-705',
			'naif-801',
			'naif-901'
		],
		kinds: [ObjectType.MOON]
	},
	{
		slug: 'visited-small-bodies',
		group: 'worlds',
		label: m.compare_preset_small_bodies,
		ids: [
			'naif-2000001',
			'spkid-20000004',
			'spkid-20000021',
			'spkid-20000253',
			'spkid-20000433',
			'spkid-20000243',
			'spkid-20000951',
			'spkid-20052246',
			'spkid-20152830',
			'spkid-20486958',
			'spkid-20065803',
			'spkid-1000012',
			'spkid-1000036',
			'spkid-1000093',
			'spkid-1000107',
			'spkid-1000041',
			'spkid-20162173',
			'spkid-20101955',
			'spkid-20025143'
		],
		kinds: SMALL_BODY_KINDS
	},
	{
		slug: 'space-stations',
		group: 'craft',
		label: m.compare_preset_stations,
		ids: [
			'norad_satcat-25544',
			'norad_satcat-16609',
			'norad_satcat-6633',
			'norad_satcat-5160',
			'norad_satcat-13138',
			'norad_satcat-37820',
			'norad_satcat-41765'
		]
	},
	{
		// One craft per design, the flight it is best known for.
		slug: 'space-capsules',
		group: 'craft',
		label: m.compare_preset_capsules,
		ids: [
			'norad_satcat-240',
			'norad_satcat-103',
			'norad_satcat-1274',
			'probe-36888576',
			'norad_satcat-28043',
			'norad_satcat-45623',
			'norad_satcat-59968'
		]
	},
	{
		// Standalone bundles rather than catalogue Objects: no kind claims them.
		slug: 'rockets',
		group: 'craft',
		label: m.compare_preset_rockets,
		ids: ROCKETS.map((r) => r.slug)
	},
	{
		slug: 'observatories',
		group: 'craft',
		label: m.compare_preset_observatories,
		ids: [
			'probe-115347456',
			'norad_satcat-20580',
			'norad_satcat-25867',
			'norad_satcat-21225',
			'norad_satcat-28485',
			'norad_satcat-33053',
			'norad_satcat-25791',
			'norad_satcat-28773',
			'norad_satcat-44874',
			'probe-112132096',
			'probe-96477185',
			'probe-96477184',
			'probe-117612544',
			'probe-103354368',
			'probe-96198656',
			'probe-109834240',
			'probe-111677440'
		]
	},
	{
		slug: 'earth-satellites',
		group: 'craft',
		label: m.compare_preset_earth_sats,
		ids: [
			'norad_satcat-25994',
			'norad_satcat-27424',
			'norad_satcat-28376',
			'norad_satcat-39084',
			'norad_satcat-25682',
			'norad_satcat-25063',
			'norad_satcat-39574',
			'norad_satcat-43613',
			'norad_satcat-37849',
			'norad_satcat-23710',
			'norad_satcat-22076',
			'norad_satcat-26997',
			'norad_satcat-25789',
			'norad_satcat-40059',
			'norad_satcat-24883',
			'norad_satcat-27391',
			'norad_satcat-27386'
		],
		// The kin an Earth satellite with no set of its own is offered: far
		// likelier one of these than one of the three stations.
		kinds: [ObjectType.SPACECRAFT],
		idPrefixes: ['norad_satcat-']
	},
	{
		slug: 'sun-watchers',
		group: 'craft',
		label: m.compare_preset_sun,
		ids: [
			'probe-76357632',
			'norad_satcat-36395',
			'probe-92659712',
			'norad_satcat-29479',
			'norad_satcat-27370',
			'probe-68640768',
			'probe-78942208',
			'probe-74735616'
		]
	},
	{
		slug: 'inner-probes',
		group: 'probes',
		label: m.compare_preset_inner_probes,
		ids: [
			'probe-66510848',
			'probe-89325568',
			'probe-110526464',
			'probe-110587904',
			'probe-110309376',
			'probe-112545792',
			'probe-53637120',
			'probe-31408128',
			'probe-33755136',
			'probe-50577409',
			'probe-61759489'
		]
	},
	{
		slug: 'mars-orbiters',
		group: 'probes',
		label: m.compare_preset_mars_orbiters,
		ids: [
			'probe-93536256',
			'probe-84353024',
			'probe-90857472',
			'probe-120983552',
			'probe-80715776',
			'probe-109281280',
			'probe-80879616',
			'probe-39677952',
			'probe-29962240'
		]
	},
	{
		slug: 'landers',
		group: 'probes',
		label: m.compare_preset_landers,
		ids: [
			'probe-100265984',
			'probe-113246208',
			'probe-87605248',
			'probe-87719936',
			'probe-109899776',
			'probe-47378432',
			'probe-47562752',
			'probe-89915392',
			'probe-88694784',
			'norad_satcat-5667',
			'probe-80977920',
			'probe-77860864',
			'norad_satcat-1954',
			'norad_satcat-4691',
			'probe-36904960',
			'probe-103280641',
			'probe-111718400',
			'probe-117669889',
			'probe-117665794',
			'probe-117895168',
			'probe-111099904',
			'probe-117776384'
		]
	},
	{
		slug: 'small-body-probes',
		group: 'probes',
		label: m.compare_preset_small_body_craft,
		ids: [
			'probe-88698880',
			'probe-107429888',
			'probe-81117184',
			'probe-89989120',
			'probe-77094912',
			'probe-101912576',
			'probe-61775872',
			'norad_satcat-25508',
			'probe-120614912',
			'probe-115220480'
		]
	},
	{
		slug: 'outer-probes',
		group: 'probes',
		label: m.compare_preset_probes,
		ids: [
			'probe-49065984',
			'probe-49000448',
			'probe-40910848',
			'probe-42479616',
			'probe-76308480',
			'probe-88592384',
			'probe-104804352',
			'probe-107159552',
			'probe-117293056',
			'probe-119541760',
			'probe-75771904'
		],
		kinds: [ObjectType.SPACECRAFT],
		idPrefixes: ['probe-']
	}
];

/** The presets under their headings, in order. */
export const COMPARE_PRESET_GROUPS = (
	[
		{ id: 'worlds', label: m.compare_preset_group_worlds },
		{ id: 'craft', label: m.compare_preset_group_craft },
		{ id: 'probes', label: m.compare_preset_group_probes }
	] satisfies { id: PresetGroup; label: () => string }[]
).map((group) => ({ ...group, presets: COMPARE_PRESETS.filter((p) => p.group === group.id) }));

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
