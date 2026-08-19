/** The drawer's surface-features model: the body's gazetteer entries, the
 *  quadrangle grid the Surface tab's hero draws, and the focused feature's
 *  type page. */

import { untrack } from 'svelte';
import { STRIP_CAPACITY } from '../members/MemberStrip.svelte';
import { tabHref } from '$lib/state/focus-link';
import type { OverviewStrip } from './members-state.svelte';
import * as m from '$lib/paraglide/messages.js';
import {
	fetchBodyQuadrangles,
	fetchQuadrangleText,
	type Quadrangle,
	type QuadrangleText
} from '$lib/fetch/nomenclature/quadrangles';
import { featureTypeSlug } from '$lib/fetch/groups/registry';
import { featureTypeLabel } from '$lib/format/feature-type';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { NotableMemberEntry, ObjectDetailData } from '$lib/fetch/objects/object-data';
import type { AppState } from '$lib/state/app-state.svelte';
import type { Focusable } from '$lib/state/focusable';

type FocusedFeature = Extract<Focusable, { kind: 'feature' }>['feature'];

export interface SurfaceStateDeps {
	isGroupMode: () => boolean;
	isFeatureMode: () => boolean;
	feature: () => FocusedFeature | null;
	bodyId: () => string | undefined;
	data: () => ObjectDetailData | null;
	appState: () => AppState;
}

export class SurfaceState {
	/** The focused feature's type page (`ft-<slug>`), for the breadcrumb +
	 *  cross-ref tile. The slug lives in the group index, so it resolves
	 *  asynchronously; untracked so writing the result doesn't re-run the lookup. */
	featureType = $state<{ slug: string; label: string } | null>(null);

	// A body's own IAU surface features. The strip is the top few; the tab holds
	// the full gazetteer for that body (Mars alone has ~2k).
	readonly notableFeatures: NotableMemberEntry[] | undefined;
	readonly featureNames: Record<string, string> | undefined;
	readonly featureTotal: number;
	readonly hasFeatures: boolean;
	readonly showFeaturesTab: boolean;
	// The overview's features strip: same card UI as the member strips, but
	// focusing a row flies to a point on this body rather than to another object.
	readonly featuresStrip: OverviewStrip | null;
	// The Surface tab's hero needs a map texture; the IAU chart grid is a bonus
	// only Mercury, Venus, Mars and the Moon carry.
	readonly showSurfaceHero: boolean;

	quadrangles = $state<Quadrangle[] | null>(null);
	// Only honoured while the hero is up, so a stale `&quad=` can't silently
	// filter the list on a body with no grid.
	readonly selectedQuad: string | null;
	readonly selectedQuadCount: number | undefined;
	// Feature the list is hovering — the hero marks it on the map.
	hoveredFeatureId = $state<number | null>(null);
	// Wikipedia intro for the picked chart. A quadrangle is a part of its body,
	// not a page of its own, so this is all there is to say about one; the
	// per-language file only loads once one is picked.
	quadText = $state<QuadrangleText | null>(null);

	constructor(d: SurfaceStateDeps) {
		$effect(() => {
			const code = d.feature()?.typeCode;
			if (!code) {
				this.featureType = null;
				return;
			}
			untrack(() => {
				featureTypeSlug(code).then((slug) => {
					if (d.feature()?.typeCode !== code) return;
					const label = featureTypeLabel(slug);
					this.featureType = slug && label ? { slug, label } : null;
				});
			});
		});

		this.notableFeatures = $derived.by(() => {
			const hidden = d.isGroupMode() || d.isFeatureMode();
			return hidden ? undefined : d.data()?.global?.notable_features;
		});
		this.featureNames = $derived(d.data()?.localized?.notable_feature_names);
		this.featureTotal = $derived(d.data()?.global?.feature_count ?? 0);
		this.hasFeatures = $derived(!!this.notableFeatures && this.notableFeatures.length > 0);
		this.showFeaturesTab = $derived(this.hasFeatures && this.featureTotal > STRIP_CAPACITY);
		this.featuresStrip = $derived.by(() => {
			if (!this.notableFeatures?.length) return null;
			return {
				members: this.notableFeatures,
				localizedNames: this.featureNames,
				totalCount: this.featureTotal,
				heading: m.features_section(),
				seeAllHref: tabHref(d.appState(), 'features'),
				onSeeAll: () => d.appState().setTab('features')
			};
		});
		this.showSurfaceHero = $derived(
			!d.isGroupMode() &&
				!d.isFeatureMode() &&
				this.hasFeatures &&
				!!d.data()?.global?.map_texture_available
		);

		$effect(() => {
			const hidden = d.isGroupMode() || d.isFeatureMode();
			const id = hidden ? null : d.bodyId();
			if (!id || !this.hasFeatures) {
				this.quadrangles = null;
				return;
			}
			let live = true;
			untrack(() => fetchBodyQuadrangles(id)).then((q) => {
				if (live) this.quadrangles = q;
			});
			return () => {
				live = false;
			};
		});

		this.selectedQuad = $derived(
			this.quadrangles?.some((q) => q.code === d.appState().view.quad)
				? d.appState().view.quad
				: null
		);
		const selectedQuadEntry = $derived(this.quadrangles?.find((q) => q.code === this.selectedQuad));
		this.selectedQuadCount = $derived(selectedQuadEntry?.n);

		$effect(() => {
			const id = d.bodyId();
			const code = this.selectedQuad;
			const lang = getLocale();
			if (!id || !code) {
				this.quadText = null;
				return;
			}
			let live = true;
			untrack(() => fetchQuadrangleText(id, code, lang)).then((t) => {
				if (live) this.quadText = t;
			});
			return () => {
				live = false;
			};
		});
	}
}
