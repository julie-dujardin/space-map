<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { buildRows, kindSummary, rootSlugs, type RingRow } from '$lib/rings/catalog';
	import { ringBarWindow } from '$lib/rings/overview-bar';
	import { formatRingMass } from '$lib/rings/stats';
	import { formatKm } from '$lib/format/distance';
	import { isModifiedClick, tabHref } from '$lib/state/focus-link';
	import type { PositionedBody } from '$lib/types/objects';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import RingOverviewBar from '../charts/RingOverviewBar.svelte';

	interface Props {
		global: GlobalObjectData | null;
		body?: PositionedBody;
	}

	let { global, body }: Props = $props();

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

	let win = $derived(features ? ringBarWindow(features) : null);
	// The one system-wide figure worth repeating outside the Rings tab: the
	// span and the named rings are the chart beside it, but the mass is not.
	let mass = $derived(global?.ring_stats?.mass ? formatRingMass(global.ring_stats.mass) : null);

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

		<Row label={m.rings_width()} value={formatKm(extent.outer - extent.inner)} />
		<Row label={m.rings_sections()} value={kindSummary(rows, roots)} />
		{#if mass}
			<Row label={m.property_name_mass()}>
				<!-- The ± hangs off the figure, not the label: it qualifies that
				     number rather than what the row is about. -->
				{#if mass.note}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<span class="cursor-help underline decoration-dotted underline-offset-2" {...props}>
									{mass.value}
								</span>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{mass.note}</Tooltip.Content>
					</Tooltip.Root>
					{mass.unit}
				{:else}
					{mass.value} {mass.unit}
				{/if}
			</Row>
		{/if}
	</Section>
{/if}
