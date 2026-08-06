<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { buildRows, kindSummary, rootSlugs, type RingRow } from '$lib/rings/catalog';
	import { ringBarWindow } from '$lib/rings/overview-bar';
	import { formatKm, formatKmRange } from '$lib/format/distance';
	import { isModifiedClick, tabHref } from '$lib/state/focus-link';
	import type { PositionedBody } from '$lib/types/objects';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import RingOverviewBar from '../charts/RingOverviewBar.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		body?: PositionedBody;
	}

	let { global, localized, body }: Props = $props();

	const appState = getContext<AppState>('appState');

	let features = $derived(global?.ring_features);
	let rows = $derived(features ? buildRows(features) : new Map<string, RingRow>());
	let roots = $derived(rootSlugs(rows));

	/** How far the system reaches, catalogue and all — the bar may stop short of
	 *  this, which is what the closing note is for. */
	let extent = $derived.by(() => {
		let inner = Infinity;
		let outer = -Infinity;
		for (const row of rows.values()) {
			inner = Math.min(inner, row.inner);
			outer = Math.max(outer, row.outer);
		}
		return outer > inner ? { inner, outer } : null;
	});

	// The system's headline ring, by the one number every catalogue publishes.
	// Top level only: naming a region of the B ring over the B ring itself would
	// answer a question nobody asked, and gaps are clearings rather than rings.
	let densest = $derived.by(() => {
		let best: RingRow | null = null;
		let peak = 0;
		for (const slug of roots) {
			const row = rows.get(slug)!;
			if (row.feature.kind === 'gap' || row.feature.kind === 'division') continue;
			const tau = row.feature.optical_depth;
			const value = tau?.high ?? tau?.low ?? 0;
			if (value > peak) {
				peak = value;
				best = row;
			}
		}
		return best;
	});
	let densestName = $derived(
		densest ? (localized?.ring_features?.[densest.slug]?.name ?? densest.feature.name) : null
	);

	let win = $derived(features ? ringBarWindow(features) : null);

	let ringsHref = $derived(tabHref(appState, 'rings'));
	function openRings(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setTab('rings');
	}
</script>

{#if features && roots.length && extent}
	<Section
		title={m.tab_rings()}
		activateHref={ringsHref}
		onActivate={openRings}
		activateLabel={m.rings_see_all()}
	>
		{#snippet header()}
			{#if win && body}
				<!-- The picture opens the same tab as "See all rings" beside it, which
				     is where the accessible name and the tab stop live. -->
				<a
					href={ringsHref}
					onclick={openRings}
					tabindex="-1"
					aria-hidden="true"
					class="hover:ring-border mt-2 mb-1.5 block rounded-sm hover:ring-1"
				>
					<RingOverviewBar {features} window={win} bodyId={body.data.id} />
				</a>
			{/if}
		{/snippet}

		<Row
			label={m.rings_extent()}
			tooltip={m.tooltip_rings_extent()}
			value={formatKmRange(extent.inner, extent.outer)}
		/>
		<Row label={m.rings_width()} value={formatKm(extent.outer - extent.inner)} />
		<Row label={m.rings_sections()} value={kindSummary(rows, roots)} />
		{#if densestName}
			<Row label={m.rings_densest()} value={densestName} />
		{/if}
		{#if win?.cut}
			<dd class="text-muted-foreground col-span-2 -mt-1.5 text-[11px] leading-snug">
				{m.rings_bar_cut({ radius: formatKm(win.outer) })}
			</dd>
		{/if}
	</Section>
{/if}
