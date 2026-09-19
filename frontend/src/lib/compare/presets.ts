/**
 * Ready-made comparisons. A set drawn on one scale only says something when
 * its members are within reach of each other, so these are the sets worth
 * opening the page on: a family, at a size a single row can hold.
 */

import * as m from '$lib/paraglide/messages.js';

export interface ComparePreset {
	slug: string;
	label: () => string;
	/** Object ids, in no particular order: the row sorts by size. */
	ids: string[];
}

export const COMPARE_PRESETS: ComparePreset[] = [
	{
		slug: 'terrestrial-planets',
		label: m.compare_preset_terrestrial,
		ids: ['naif-199', 'naif-299', 'naif-399', 'naif-499', 'naif-301']
	},
	{
		slug: 'giant-planets',
		label: m.compare_preset_giants,
		ids: ['naif-599', 'naif-699', 'naif-799', 'naif-899']
	},
	{
		slug: 'galilean-moons',
		label: m.compare_preset_galilean,
		ids: ['naif-501', 'naif-502', 'naif-503', 'naif-504']
	},
	{
		slug: 'large-moons',
		label: m.compare_preset_large_moons,
		ids: ['naif-503', 'naif-606', 'naif-504', 'naif-501', 'naif-301', 'naif-502', 'naif-701']
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
		]
	},
	{
		slug: 'space-stations',
		label: m.compare_preset_stations,
		ids: ['norad_satcat-25544', 'norad_satcat-16609', 'norad_satcat-6633']
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
		]
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
