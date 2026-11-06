/** The interior of the drawer's star: its Interior row, the block that the
 *  Structure tab draws from it, and the credits of that block. */

import { untrack } from 'svelte';
import { fetchStarInterior, type StarInterior } from '$lib/fetch/extrasolar/interior';
import { POINT_SOURCE_SLUG, homeRow, type ExtrasolarRecord } from '$lib/fetch/extrasolar/lookup';
import { isStarSystem } from '$lib/fetch/extrasolar/systems';
import type { GlobalObjectData, InteriorBlock } from '$lib/fetch/objects/object-data';
import { starInteriorBlock } from '$lib/charts/star-interior';
import { starRadiusKm, starTeff } from '$lib/scene/starfield/record';
import { starInteriorCredits, type StarCredit } from '$lib/credits/star-sources';

/** What the Structure tab of a star needs. */
export interface StarStructure {
	interior: StarInterior;
	block: InteriorBlock;
	/** The effective temperature, K: the row's, which the zones were fitted
	 *  to, else the record's. The block's own surface temperature wins. */
	surfaceK: number | null;
	credits: StarCredit[];
}

/** Whether a record can have an Interior row worth a lookup. A node of a star
 *  system shines with the light of two stars, so the scene gives it no
 *  radius, and the panel draws no interior for it. */
export function interiorShown(record: ExtrasolarRecord): boolean {
	return record.home === POINT_SOURCE_SLUG && !isStarSystem(record);
}

export class StarInteriorLoad {
	interior = $state.raw<StarInterior | null>(null);
	/** True while the row of the current star is on its way. */
	loading = $state(false);
	readonly structure: StarStructure | null;

	/** `references` are the papers of the star's object entry. */
	constructor(
		record: () => ExtrasolarRecord | null,
		references: () => GlobalObjectData['references']
	) {
		this.structure = $derived.by(() => {
			const current = record();
			const interior = this.interior;
			if (!current || !interior || interior.id !== current.id) return null;
			const home = homeRow(current);
			const block = starInteriorBlock(interior, home && starRadiusKm(home));
			if (!block) return null;
			return {
				interior,
				block,
				surfaceK: interior.teff ?? (home && starTeff(home)),
				credits: starInteriorCredits(interior, current, references())
			};
		});
		// The ID alone: a new record of the same star needs no new fetch.
		const id = $derived(record()?.id);
		$effect(() => {
			const star = id;
			const current = untrack(record);
			this.interior = null;
			if (star === undefined || !current || !interiorShown(current)) {
				this.loading = false;
				return;
			}
			this.loading = true;
			let live = true;
			untrack(() => fetchStarInterior(star)).then(
				(interior) => {
					if (!live) return;
					this.interior = interior;
					this.loading = false;
				},
				(e: unknown) => {
					if (!live) return;
					console.warn(`[interior] no interior for ${star}:`, e);
					this.loading = false;
				}
			);
			return () => {
				live = false;
			};
		});
	}
}
