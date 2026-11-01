/** Shape of the drill-down filter tree (built in SearchBar from the live facet
 *  distribution + the group catalog, consumed by FilterDrill). */

import {
	CAT_CONSTELLATIONS,
	CAT_DEBRIS,
	CAT_PLANETARY_SYSTEMS,
	CAT_PROBES,
	CAT_SATELLITES,
	CAT_STARS,
	CAT_SURFACE_FEATURES,
	type GroupType
} from '$lib/fetch/groups/registry';
import type { ArrayFacet, BoolFacet, RangeFacet } from './model.svelte';

/** A toggleable filter option. An array leaf may carry several raw values (a
 *  All of a class that spans types). */
export type FilterLeaf = {
	id: string;
	label: string;
	count?: number;
} & ({ kind: 'array'; facet: ArrayFacet; values: string[] } | { kind: 'bool'; facet: BoolFacet });

/** Leaves listed in place rather than drilled into, after the drillable
 *  `children`, under a heading or set off by a rule. */
export interface FilterSection {
	id: string;
	label?: string;
	leaves: FilterLeaf[];
}

/** A node in the filter drill tree. The root's `children` are the type nodes
 *  (Planets, Asteroids, Spacecraft, …). A node may offer direct toggle `leaves`
 *  (All / NEO / PHA), `sections` of them, drillable `children` (Orbit class,
 *  Organization, …) and/or numeric `ranges` (rendered as sliders); `count` is
 *  the type total shown on the drill row. */
export interface FilterNode {
	id: string;
	label: string;
	count?: number;
	leaves?: FilterLeaf[];
	sections?: FilterSection[];
	children?: FilterNode[];
	ranges?: RangeFacet[];
}

/** The Collections filter: each type under the category page it browses from.
 *  `category` has no such page, and sits above these. */
export const COLLECTION_SECTIONS: readonly {
	category: string;
	types: readonly (GroupType | 'fleet' | 'breakup_cloud')[];
}[] = [
	{
		category: CAT_PLANETARY_SYSTEMS,
		types: ['planet_family', 'orbit_class', 'split_comet', 'small_body_flag']
	},
	{ category: CAT_STARS, types: ['star_family'] },
	{ category: CAT_CONSTELLATIONS, types: ['sky_culture', 'sky_constellation'] },
	{ category: CAT_SURFACE_FEATURES, types: ['feature_type'] },
	{
		category: CAT_SATELLITES,
		types: ['fleet', 'earth_orbit_class', 'organization', 'country', 'bus', 'launch_site']
	},
	{ category: CAT_DEBRIS, types: ['launch_vehicle', 'breakup_cloud'] },
	{ category: CAT_PROBES, types: ['mission'] }
];
