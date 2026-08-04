/** Per-category-slug drawer presentation, so the slug knowledge lives in one
 *  table instead of a dozen scattered `slug === CAT_*` derivations. */

import {
	CAT_PLANETS,
	CAT_MOONS,
	CAT_DWARF_PLANETS,
	CAT_SOLAR_SYSTEM,
	CAT_ASTEROIDS,
	CAT_COMETS,
	CAT_SATELLITES,
	CAT_DEBRIS,
	CAT_PROBES,
	CAT_RING_SYSTEMS
} from '$lib/fetch/groups/registry';
import type { Focusable } from '$lib/state/focusable';

export interface CategoryConfig {
	planets: boolean;
	moons: boolean;
	dwarfPlanets: boolean;
	solarSystem: boolean;
	/** Members are the ringed bodies, shown as tiles onto their Rings tab. */
	ringSystems: boolean;
	/** planets/moons/dwarf: hero is a sphere lineup, so no member strip. */
	lineup: boolean;
	/** The overview already shows every member — the lineup for planets and
	 *  dwarfs, the tiles for ring systems — so a members tab would just repeat
	 *  it. Moons show only the notable few, so they keep one. */
	membersShownInFull: boolean;
	/** asteroids/comets: members route through the members tab, no overview strip. */
	smallBody: boolean;
	/** Opts the page into the sphere-lineup hero. Off by default: a row of
	 *  spheres is a picture of the *bodies*, which is only the subject on a page
	 *  that collects bodies — the ring systems page collects what orbits them.
	 *  The small-body zones and families opt in through `applies_to` instead,
	 *  since they have no entry here. */
	sphereLineup: boolean;
	/** Page cross-links its sibling collections. */
	crossRefs: boolean;
}

const NONE: CategoryConfig = {
	planets: false,
	moons: false,
	dwarfPlanets: false,
	solarSystem: false,
	ringSystems: false,
	lineup: false,
	membersShownInFull: false,
	smallBody: false,
	sphereLineup: false,
	crossRefs: false
};

const BY_SLUG: Record<string, Partial<CategoryConfig>> = {
	[CAT_PLANETS]: { planets: true, lineup: true, membersShownInFull: true, crossRefs: true },
	[CAT_MOONS]: { moons: true, lineup: true, crossRefs: true },
	[CAT_RING_SYSTEMS]: { ringSystems: true, membersShownInFull: true },
	[CAT_DWARF_PLANETS]: {
		dwarfPlanets: true,
		lineup: true,
		membersShownInFull: true,
		crossRefs: true
	},
	[CAT_SOLAR_SYSTEM]: { solarSystem: true },
	[CAT_ASTEROIDS]: { smallBody: true, sphereLineup: true, crossRefs: true },
	[CAT_COMETS]: { smallBody: true, sphereLineup: true, crossRefs: true },
	[CAT_SATELLITES]: { crossRefs: true },
	[CAT_DEBRIS]: { crossRefs: true },
	[CAT_PROBES]: { crossRefs: true }
};

// Merged configs, cached per slug so a stable reference comes back each call: a
// fresh object would churn every `$derived` that reads it whenever the focusable
// identity changes (the 500ms date tick reassigns `view`), needlessly rebuilding
// the sphere lineup ~2×/s.
const CONFIG_BY_SLUG = new Map<string, CategoryConfig>(
	Object.entries(BY_SLUG).map(([slug, cfg]) => [slug, { ...NONE, ...cfg }])
);

export function categoryConfig(focusable: Focusable): CategoryConfig {
	if (focusable.kind !== 'group') return NONE;
	return CONFIG_BY_SLUG.get(focusable.slug) ?? NONE;
}
