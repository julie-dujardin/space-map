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

/** A drillable group of leaves (Kind, Type, Orbit class, Constellation, …). */
export interface FilterCategory {
	id: string;
	label: string;
	leaves: FilterLeaf[];
}
