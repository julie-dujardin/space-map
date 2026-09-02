/** Per-category-slug drawer presentation, so the slug knowledge lives in one
 *  table instead of a dozen scattered `slug === CAT_*` derivations. */

import {
	CAT_PLANETS,
	CAT_MOONS,
	CAT_DWARF_PLANETS,
	CAT_SOLAR_SYSTEM,
	CAT_SATELLITE_SYSTEMS,
	CAT_ASTEROIDS,
	CAT_COMETS,
	CAT_SATELLITES,
	CAT_DEBRIS,
	CAT_PROBES,
	CAT_RING_SYSTEMS,
	CAT_ATMOSPHERES,
	CAT_OCEANS,
	CAT_VOLCANISM,
	CAT_TECTONICS,
	CAT_MAGNETIC_FIELDS,
	CAT_TIDAL_HEATING,
	CAT_RADIATION
} from '$lib/fetch/groups/registry';
import type { Focusable } from '$lib/state/focusable';

export interface CategoryConfig {
	planets: boolean;
	moons: boolean;
	dwarfPlanets: boolean;
	solarSystem: boolean;
	/** Members are the barycenter pages, named "<primary> system" off the
	 *  primary's label and shown as one map tile each. */
	satelliteSystems: boolean;
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
	/** A Structure & Activity collection, and which property it is about. Its
	 *  overview lists every member drawn as that property — a cutaway, a limb —
	 *  rather than photographed, so there is no member strip and no members tab. */
	property: PropertyKind | null;
}

/** The Structure & Activity collections, by what their members carry. */
export type PropertyKind =
	| 'atmospheres'
	| 'oceans'
	| 'volcanism'
	| 'tectonics'
	| 'magnetic-fields'
	| 'tidal-heating'
	| 'radiation';

const NONE: CategoryConfig = {
	planets: false,
	moons: false,
	dwarfPlanets: false,
	solarSystem: false,
	satelliteSystems: false,
	ringSystems: false,
	lineup: false,
	membersShownInFull: false,
	smallBody: false,
	sphereLineup: false,
	crossRefs: false,
	property: null
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
	[CAT_SATELLITE_SYSTEMS]: { satelliteSystems: true, membersShownInFull: true },
	[CAT_ASTEROIDS]: { smallBody: true, sphereLineup: true, crossRefs: true },
	[CAT_COMETS]: { smallBody: true, sphereLineup: true, crossRefs: true },
	[CAT_SATELLITES]: { crossRefs: true },
	[CAT_DEBRIS]: { crossRefs: true },
	[CAT_PROBES]: { crossRefs: true },
	// Every member is listed in the overview with its own drawing, so the tab
	// would repeat the page — the same reason the ring systems have none.
	[CAT_ATMOSPHERES]: { property: 'atmospheres', membersShownInFull: true },
	[CAT_OCEANS]: { property: 'oceans', membersShownInFull: true },
	[CAT_VOLCANISM]: { property: 'volcanism', membersShownInFull: true },
	[CAT_TECTONICS]: { property: 'tectonics', membersShownInFull: true },
	[CAT_MAGNETIC_FIELDS]: { property: 'magnetic-fields', membersShownInFull: true },
	[CAT_TIDAL_HEATING]: { property: 'tidal-heating', membersShownInFull: true },
	[CAT_RADIATION]: { property: 'radiation', membersShownInFull: true }
};

// Merged configs, cached per slug so a stable reference comes back each call: a
// fresh object would churn every `$derived` that reads it whenever the focusable
// identity changes (the 500ms date tick reassigns `view`), needlessly rebuilding
// the sphere lineup ~2×/s.
const CONFIG_BY_SLUG = new Map<string, CategoryConfig>(
	Object.entries(BY_SLUG).map(([slug, cfg]) => [slug, { ...NONE, ...cfg }])
);

/**
 * The interior shell each property page is about, drawn with a floor on its
 * thickness so a thin one still reads at tile size.
 *
 * Where each page's subject happens: the melt comes out of the mantle, the
 * dynamo runs in the core, and the tide is dissipated in the soft middle.
 * Atmospheres have no interior layer to lift — their members draw a limb.
 */
export const PROPERTY_ACCENT: Record<PropertyKind, ReadonlySet<string> | undefined> = {
	atmospheres: undefined,
	oceans: new Set(['ocean']),
	volcanism: new Set(['mantle', 'asthenosphere', 'magma_ocean']),
	// Tectonics happens in the outer solid shell, whether that is rock or ice.
	tectonics: new Set(['crust', 'oceanic_crust', 'ice_shell']),
	'magnetic-fields': new Set(['core', 'outer_core', 'inner_core', 'metallic_hydrogen']),
	'tidal-heating': new Set(['mantle', 'ocean']),
	// The dose is taken on the outside, so the shell that takes it is the same
	// one tectonics lifts — rock or ice, whichever the body ends in.
	radiation: new Set(['crust', 'oceanic_crust', 'ice_shell'])
};

export function categoryConfig(focusable: Focusable): CategoryConfig {
	if (focusable.kind !== 'group') return NONE;
	return CONFIG_BY_SLUG.get(focusable.slug) ?? NONE;
}

/**
 * The Structure & Activity collections, read off the table above rather than
 * listed again — a second list is one a new page gets left out of. Both the
 * breadcrumb (which climbs these to the meta node instead of the Solar System
 * root) and its test went stale that way, and the page they both missed
 * breadcrumbed past its own parent.
 */
export const PROPERTY_COLLECTION_SLUGS: readonly string[] = [...CONFIG_BY_SLUG]
	.filter(([, cfg]) => cfg.property != null)
	.map(([slug]) => slug);

export function isPropertyCollection(slug: string): boolean {
	return CONFIG_BY_SLUG.get(slug)?.property != null;
}
