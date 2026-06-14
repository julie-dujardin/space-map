/** Shape of the drill-down filter tree (built in SearchBar from the live facet
 *  distribution + the group catalog, consumed by FilterDrill). */

import type { ArrayFacet, BoolFacet } from './model.svelte';

/** A toggleable filter option. An array leaf may carry several raw values (a
 *  merged "Asteroid" leaf maps to every `asteroid_*` type). */
export type FilterLeaf = {
	id: string;
	label: string;
	count?: number;
} & ({ kind: 'array'; facet: ArrayFacet; values: string[] } | { kind: 'bool'; facet: BoolFacet });

/** A node in the filter drill tree. The root's `children` are the type nodes
 *  (Planets, Asteroids, Spacecraft, …). A node may offer direct toggle `leaves`
 *  (All / NEO / PHA) and/or drillable `children` (Orbit class, Organization, …);
 *  `count` is the type total shown on the drill row. */
export interface FilterNode {
	id: string;
	label: string;
	count?: number;
	leaves?: FilterLeaf[];
	children?: FilterNode[];
}
