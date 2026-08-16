<script lang="ts">
	/**
	 * How much material each ring system holds, on a log scale — the answer
	 * spans fourteen decades (Saturn outweighs Jupiter by a trillion), so a
	 * linear share-of-largest bar would leave every other system at zero width.
	 */

	import type { NotableMemberEntry } from '$lib/fetch/objects/object-data';
	import { formatRingMass } from '$lib/rings/stats';
	import * as m from '$lib/paraglide/messages.js';
	import CountPerBodyChart, { type CountPerBodyEntry } from './CountPerBodyChart.svelte';

	interface Props {
		members: NotableMemberEntry[];
		localizedNames?: Record<string, string>;
	}
	let { members, localizedNames }: Props = $props();

	function name(entry: NotableMemberEntry): string {
		return localizedNames?.[entry.id ?? ''] ?? entry.name;
	}

	let masses = $derived(
		new Map(
			members
				.filter((entry) => entry.id && entry.ring_mass)
				.map((entry) => [entry.id as string, entry.ring_mass!])
		)
	);

	// `n` is where the bar ends. A range plots at its geometric mean, the middle
	// of the span on a log axis; Jupiter's two published decades would otherwise
	// draw at whichever end was picked.
	let entries = $derived.by<CountPerBodyEntry[]>(() =>
		members
			.filter((entry) => entry.id && masses.has(entry.id))
			.map((entry) => {
				const mass = masses.get(entry.id as string)!;
				return {
					name: name(entry),
					primary_type: 'object' as const,
					primary_id: entry.id as string,
					n: mass.high_kg ? Math.sqrt(mass.low_kg * mass.high_kg) : mass.low_kg
				};
			})
			.sort((a, b) => b.n - a.n)
	);

	/** Systems the page lists but no source puts a number on. */
	let unmeasured = $derived(
		members.filter((entry) => entry.id && !entry.ring_mass).map((entry) => name(entry))
	);

	// A decade of headroom under the lightest system so its bar is still a bar
	// rather than the zero-width sliver an exact floor would leave it.
	let scale = $derived.by(() => {
		if (!entries.length) return null;
		const low = Math.floor(Math.log10(Math.min(...entries.map((e) => e.n)))) - 1;
		const high = Math.ceil(Math.log10(Math.max(...entries.map((e) => e.n))));
		return { low, span: high - low };
	});

	function fraction(entry: CountPerBodyEntry): number {
		if (!scale) return 0;
		return Math.min(1, Math.max(0, (Math.log10(entry.n) - scale.low) / scale.span));
	}

	function text(entry: CountPerBodyEntry): string {
		const mass = masses.get(entry.primary_id ?? '');
		if (!mass) return '';
		const { number, unit } = formatRingMass(mass);
		return `${number} ${unit}`;
	}
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<CountPerBodyChart
			{entries}
			{fraction}
			{text}
			title={m.group_ring_mass_title()}
			hint={m.chart_log_scale()}
			tab="rings"
		/>
		{#if unmeasured.length > 0}
			<p class="text-muted-foreground text-xs">
				{m.group_ring_mass_unknown({ names: unmeasured.join(', ') })}
			</p>
		{/if}
	</div>
{/if}
