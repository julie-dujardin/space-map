<script lang="ts">
	/**
	 * One log-scaled bar per member, for every collection page whose answer is a
	 * number: pressure, water, field strength, heat.
	 *
	 * One component rather than one per page because the shape is identical and
	 * only the accessors differ — each spans decades, so a share of the largest
	 * would leave most of the set at zero width, and each has members nobody has
	 * put a figure on, which are named in a footnote rather than drawn as empty
	 * rows.
	 */
	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import * as m from '$lib/paraglide/messages.js';
	import CountPerBodyChart, { type CountPerBodyEntry } from './CountPerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
		title: string;
		/** The figure to plot, or undefined for a member with none. A published
		 *  bound is not a measurement and returns undefined here — Titan's field
		 *  is how tightly nobody found one. */
		value: (member: NotableMemberEntry) => number | undefined;
		/** How that figure reads beside its bar. */
		text: (value: number) => string;
		/** A second reading of the same figure, hung off it — the ocean volumes
		 *  against Earth's. */
		tooltip?: (value: number) => string | undefined;
		/** Opens the footnote, ahead of the unmeasured members: what the figures
		 *  are quoted at, where that is not the same for every row. */
		note?: string;
	}
	let { members, localizedNames, title, value, text, tooltip, note }: Props = $props();

	function name(entry: NotableMemberEntry): string {
		return localizedNames?.[entry.id ?? ''] ?? entry.name;
	}

	let plotted = $derived(
		members
			.filter((entry) => entry.id)
			.map((entry) => ({ entry, n: value(entry) }))
			.filter((row): row is { entry: NotableMemberEntry; n: number } => row.n != null && row.n > 0)
	);

	let entries = $derived.by<CountPerBodyEntry[]>(() =>
		plotted
			.map(({ entry, n }) => ({
				name: name(entry),
				primary_type: 'object' as const,
				primary_id: entry.id as string,
				color: entry.color,
				n
			}))
			.sort((a, b) => b.n - a.n)
	);

	let unmeasured = $derived(
		members
			.filter((entry) => entry.id && !plotted.some((row) => row.entry.id === entry.id))
			.map(name)
	);

	// Linear: the bar is the value as a share of the largest, which is what a
	// bar length means to anyone who has not been told otherwise.
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<CountPerBodyChart
			{entries}
			{title}
			text={(e) => text(e.n)}
			tooltip={tooltip ? (e) => tooltip(e.n) : undefined}
			tab="structure"
		/>
		{#if note || unmeasured.length > 0}
			<p class="text-muted-foreground text-xs">
				{note ?? ''}{#if unmeasured.length > 0}{m.group_chart_unmeasured({
						names: unmeasured.join(', ')
					})}{/if}
			</p>
		{/if}
	</div>
{/if}
