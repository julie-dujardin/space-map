/** Per-category-slug drawer presentation, so the slug knowledge lives in one
 *  table instead of a dozen scattered `slug === CAT_*` derivations. */

import {
	CAT_PLANETS,
	CAT_MOONS,
	CAT_DWARF_PLANETS,
	CAT_SOLAR_SYSTEM,
	CAT_ASTEROIDS,
	CAT_COMETS
} from '$lib/fetch/groups/registry';
import type { Focusable } from '$lib/state/focusable';

export interface CategoryConfig {
	planets: boolean;
	moons: boolean;
	dwarfPlanets: boolean;
	solarSystem: boolean;
	/** planets/moons/dwarf: hero is a sphere lineup; no member strip/tab. */
	lineup: boolean;
	/** asteroids/comets: members route through the members tab, no overview strip. */
	smallBody: boolean;
	/** Lineup + small-body pages cross-link their sibling categories. */
	crossRefs: boolean;
}

const NONE: CategoryConfig = {
	planets: false,
	moons: false,
	dwarfPlanets: false,
	solarSystem: false,
	lineup: false,
	smallBody: false,
	crossRefs: false
};

const BY_SLUG: Record<string, Partial<CategoryConfig>> = {
	[CAT_PLANETS]: { planets: true, lineup: true, crossRefs: true },
	[CAT_MOONS]: { moons: true, lineup: true, crossRefs: true },
	[CAT_DWARF_PLANETS]: { dwarfPlanets: true, lineup: true, crossRefs: true },
	[CAT_SOLAR_SYSTEM]: { solarSystem: true },
	[CAT_ASTEROIDS]: { smallBody: true, crossRefs: true },
	[CAT_COMETS]: { smallBody: true, crossRefs: true }
};

export function categoryConfig(focusable: Focusable): CategoryConfig {
	if (focusable.kind !== 'group') return NONE;
	return { ...NONE, ...BY_SLUG[focusable.slug] };
}
