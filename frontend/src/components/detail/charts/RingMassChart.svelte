<script lang="ts">
	/** How much material each ring system holds. */

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

	// `n` is where the bar ends. A range plots at its geometric mean; Jupiter's
	// two published decades would otherwise draw at whichever end was picked.
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

	function text(entry: CountPerBodyEntry): string {
		const mass = masses.get(entry.primary_id ?? '');
		if (!mass) return '';
		const { number, unit } = formatRingMass(mass);
		return `${number} ${unit}`;
	}
</script>

{#if entries.length > 0}
	<div class="flex flex-col gap-1">
		<CountPerBodyChart {entries} {text} title={m.group_ring_mass_title()} tab="rings" />
		{#if unmeasured.length > 0}
			<p class="text-muted-foreground text-xs">
				{m.group_ring_mass_unknown({ names: unmeasured.join(', ') })}
			</p>
		{/if}
	</div>
{/if}
