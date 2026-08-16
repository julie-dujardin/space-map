<script lang="ts">
	/**
	 * The Rings tab's stat trio: how much of it, how thin, when we found it.
	 * None of these restate the panel below — thickness is the one dimension
	 * the radial chart has no axis for, and mass/date aren't on it at all. A
	 * body with nothing for a slot leaves it out.
	 */

	import * as m from '$lib/paraglide/messages.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { RingStats } from '$lib/fetch/objects/object-data';
	import { formatRingMass } from '$lib/rings/stats';
	import { formatKm, formatKmRange } from '$lib/format/distance';

	interface Props {
		stats: RingStats | undefined;
	}
	let { stats }: Props = $props();

	interface Stat {
		label: string;
		value: string;
		tooltip?: string;
	}

	let massStat = $derived.by<Stat | null>(() => {
		if (!stats?.mass) return null;
		const { number, unit, note } = formatRingMass(stats.mass);
		return { label: m.property_name_mass(), value: `${number} ${unit}`, tooltip: note };
	});

	let thicknessStat = $derived.by<Stat | null>(() => {
		const value = stats?.thickness;
		if (!value) return null;
		// Stored in metres; the km formatter drops to metres under a kilometre,
		// which is where Saturn's main rings live.
		const text =
			value.high_m !== undefined
				? formatKmRange(value.low_m / 1000, value.high_m / 1000)
				: formatKm(value.low_m / 1000);
		return { label: m.rings_stat_thickness(), value: text, tooltip: m.tooltip_rings_thickness() };
	});

	// Years are labels, not quantities — no thousands separator, as the group
	// cards do it. How the rings were caught is in the article above.
	let discoveryStat = $derived.by<Stat | null>(() => {
		const year = stats?.discovery_year;
		if (!year) return null;
		return { label: m.group_stat_discovered(), value: String(year) };
	});

	let cards = $derived([massStat, thicknessStat, discoveryStat].filter((s) => s !== null));
</script>

{#snippet card(s: Stat, props: Record<string, unknown>)}
	<div
		class="border-border/60 bg-muted/40 pointer-events-auto flex flex-col gap-1 rounded-md border p-2.5 {s.tooltip
			? 'cursor-help'
			: ''}"
		{...props}
	>
		<div class="text-muted-foreground text-[10px] uppercase">{s.label}</div>
		<div class="text-sm font-semibold tabular-nums">{s.value}</div>
	</div>
{/snippet}

{#if cards.length > 0}
	<div class="grid auto-cols-fr grid-flow-col gap-2">
		{#each cards as s (s.label)}
			{#if s.tooltip}
				<Tooltip.Root>
					<Tooltip.Trigger>
						{#snippet child({ props })}{@render card(s, props)}{/snippet}
					</Tooltip.Trigger>
					<Tooltip.Content>{s.tooltip}</Tooltip.Content>
				</Tooltip.Root>
			{:else}
				{@render card(s, {})}
			{/if}
		{/each}
	</div>
{/if}
