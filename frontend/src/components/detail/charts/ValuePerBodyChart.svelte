<script lang="ts">
	/**
	 * One bar per member (pressure, water, field strength, heat) — shared across
	 * pages since only the accessors differ. Each spans decades, so a share of
	 * the largest would flatten most of the set; unmeasured members go in a
	 * footnote instead of an empty row.
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
		 *  against Earth's, what a day of a dose rate would do to somebody. The
		 *  member comes along for the readings that need more than the number,
		 *  like the shielding a dose was quoted behind. */
		tooltip?: (value: number, member: NotableMemberEntry) => string | undefined;
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

	// The chart row keeps only what it draws, so a tooltip wanting more than the
	// number reaches the member back through this.
	let byId = $derived(new Map(plotted.map(({ entry }) => [entry.id as string, entry])));

	// Linear: the bar is the value as a share of the largest, which is what a
	// bar length means to anyone who has not been told otherwise.
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<CountPerBodyChart
			{entries}
			{title}
			text={(e) => text(e.n)}
			tooltip={tooltip
				? (e) => {
						const member = byId.get(e.primary_id ?? '');
						return member ? tooltip(e.n, member) : undefined;
					}
				: undefined}
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
