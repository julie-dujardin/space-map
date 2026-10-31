/** The star system of the drawer's extrasolar object. The name of the root
 *  loads apart from the rest, as the breadcrumb needs only that. */

import { untrack } from 'svelte';
import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import type { ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { systemRoot } from '$lib/fetch/extrasolar/systems';
import { fetchPageName } from '$lib/state/page-name';
import { loadStarSystem, type StarSystem } from '$lib/state/star-system';

export class StarSystemLoad {
	/** The root of the system, once it has a name; null at the root itself. */
	root = $state.raw<{ id: number; name: string } | null>(null);
	system = $state.raw<StarSystem | null>(null);

	constructor(record: () => ExtrasolarRecord | null) {
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
