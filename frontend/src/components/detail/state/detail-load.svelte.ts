/** The drawer's one detail fetch: whichever of the three payload shapes this
 *  focusable takes, with stale-load guards. */

import { untrack } from 'svelte';
import { fetchObjectDetail, type ObjectDetailData } from '$lib/fetch/objects/object-data';
import { extrasolarObjectId, planetObjectId } from '$lib/fetch/extrasolar/ids';
import { fetchFeatureDetail, type FeatureDetailData } from '$lib/fetch/nomenclature/details';
import { fetchGroupDetail, type GroupDetailData } from '$lib/fetch/groups/details';
import type { Focusable } from '$lib/state/focusable';
import { featureDetailToObjectData, groupDetailToObjectData } from '$lib/state/detail-adapters';

export interface DetailLoadDeps {
	focusable: () => Focusable;
	/** Stable key — focusable identity churns on every view reassignment
	 *  (camera/time/replaceFocusName) and would re-fetch. */
	focusableId: () => string;
}

export class DetailLoad {
	data = $state<ObjectDetailData | null>(null);
	featureDetail = $state<FeatureDetailData | null>(null);
	groupDetail = $state<GroupDetailData | null>(null);
	loading = $state(true);
	// Set when the detail fetch rejects — drives an alert panel instead of an
	// empty drawer. `#retryNonce` re-triggers the load effect on a retry click.
	loadError = $state(false);
	#retryNonce = $state(0);

	retry = () => {
		this.#retryNonce++;
	};

	constructor(d: DetailLoadDeps) {
		$effect(() => {
			const key = d.focusableId();
			void this.#retryNonce; // re-run on retry
			const current = untrack(() => d.focusable());
			this.loading = true;
			this.loadError = false;
			this.data = null;
			this.featureDetail = null;
			this.groupDetail = null;
			// Surface a rejected fetch as an alert panel; stale loads (key moved on)
			// are ignored so an old failure can't overwrite a newer focus.
			const onError = (err: unknown) => {
				if (d.focusableId() !== key) return;
				console.warn(`[detail] failed to load ${key}:`, err);
				this.loading = false;
				this.loadError = true;
			};
			// A star's or a planet's records came with it; its text, when it has
			// any, is an object entry. Without the text the records still show.
			if (current.kind === 'star' || current.kind === 'planet') {
				const entry =
					current.kind === 'star'
						? current.record.metadata.object && extrasolarObjectId(current.record.id)
						: current.anchor.planet.object &&
							planetObjectId(current.anchor.planet.host, current.anchor.planet.number);
				if (!entry) {
					this.loading = false;
					return;
				}
				fetchObjectDetail(entry)
					.catch((err: unknown) => {
						console.warn(`[detail] no object entry for ${key}:`, err);
						return null;
					})
					.then((result) => {
						if (d.focusableId() !== key) return;
						this.data = result;
						this.loading = false;
					});
				return;
			}
			if (current.kind === 'feature') {
				const f = current.feature;
				fetchFeatureDetail(current.body.data.id, f.featureId)
					.then((detail) => {
						if (d.focusableId() !== key) return;
						this.featureDetail = detail;
						this.data = featureDetailToObjectData(detail, f);
						this.loading = false;
					})
					.catch(onError);
				return;
			}
			if (current.kind === 'group') {
				const slug = current.slug;
				fetchGroupDetail(slug)
					.then((detail) => {
						if (d.focusableId() !== key) return;
						this.groupDetail = detail;
						this.data = groupDetailToObjectData(detail, slug);
						this.loading = false;
					})
					.catch(onError);
				return;
			}
			const bodyId = current.body.data.id;
			const hasLocalized = current.body.data.hasLocalized;
			fetchObjectDetail(bodyId, hasLocalized)
				.then((result) => {
					if (d.focusableId() === key) {
						this.data = result;
						this.loading = false;
					}
				})
				.catch(onError);
		});
	}
}
