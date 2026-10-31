/** The star system of the drawer's extrasolar object. The name of the root
 *  loads apart from the rest, as the breadcrumb needs only that. */

import { untrack } from 'svelte';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import type { ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { planetCatalogue } from '$lib/fetch/extrasolar/planets';
import { isStarSystem, systemRoot } from '$lib/fetch/extrasolar/systems';
import { CAT_PLANETARY_SYSTEMS, CAT_STAR_SYSTEMS } from '$lib/fetch/groups/registry';
import { fetchPageName } from '$lib/state/page-name';
import { loadStarSystem, type StarSystem } from '$lib/state/star-system';

/** The IAU class of a planet: a brown dwarf makes no planetary system. */
const PLANET_CLASS = 'planet';

export class StarSystemLoad {
	/** The root of the system, once it has a name; null at the root itself. */
	root = $state.raw<{ id: number; name: string } | null>(null);
	system = $state.raw<StarSystem | null>(null);
	/** The record has a planet of its own. */
	hostsPlanets = $state(false);

	/** The categories of the record: a star system, a planetary system, or both
	 *  for a pair that a planet circles. */
	readonly categories: string[];

	constructor(record: () => ExtrasolarRecord | null) {
		this.categories = $derived.by(() => {
			const current = record();
			if (!current) return [];
			return [
				...(isStarSystem(current) ? [CAT_STAR_SYSTEMS] : []),
				...(this.hostsPlanets ? [CAT_PLANETARY_SYSTEMS] : [])
			];
		});
		$effect(() => {
			const id = record()?.id ?? null;
			this.hostsPlanets = false;
			if (id === null) return;
			let live = true;
			planetCatalogue.hostSystem(id).then(
				(system) => {
					if (live) {
						this.hostsPlanets = !!system?.planets.some(
							(p) => p.host === id && p.class === PLANET_CLASS
						);
					}
				},
				(e: unknown) => console.warn(`[systems] no planets for ${id}:`, e)
			);
			return () => {
				live = false;
			};
		});
		$effect(() => {
			const id = record()?.id ?? null;
			const current = untrack(record);
			this.root = null;
			this.system = null;
			const root = current && systemRoot(current);
			if (id === null || root === null) return;
			let live = true;
			if (root !== id) {
				fetchPageName({ kind: 'body', id: extrasolarObjectId(root) }).then(
					(name) => {
						if (live && name) this.root = { id: root, name };
					},
					(e: unknown) => console.warn(`[systems] no name for system ${root}:`, e)
				);
			}
			loadStarSystem(root).then(
				(system) => {
					if (live) this.system = system;
				},
				(e: unknown) => console.warn(`[systems] system ${root} did not load:`, e)
			);
			return () => {
				live = false;
			};
		});
	}
}
