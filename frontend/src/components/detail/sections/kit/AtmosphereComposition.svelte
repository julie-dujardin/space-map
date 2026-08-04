<script lang="ts" module>
	import type { AtmosphereBlock } from '$lib/fetch/objects/object-data';

	type Composition = NonNullable<AtmosphereBlock['composition']>;

	/**
	 * Everything the bar shows is a share of the species we list, so a body
	 * whose sources only pin one gas is a full bar of that gas — true, but it
	 * reads as a measurement it isn't. Two species minimum.
	 */
	export function hasCompositionBar(composition: Composition | undefined): boolean {
		return (composition?.species.length ?? 0) > 1;
	}
</script>

<script lang="ts">
	/**
	 * The atmosphere composition bar with its trace bucket and unit caption.
	 * Drawn by the Overview's Atmosphere section and by the Structure tab, so
	 * the shares can never read differently across the two.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import { compositionSegments, speciesName } from '$lib/charts/atmosphere-species';
	import type { CompositionSegment } from '$lib/charts/composition-bar';
	import { formatPercent } from '$lib/format/quantities';
	import CompositionBar from './CompositionBar.svelte';

	interface Props {
		composition: Composition | undefined;
	}

	let { composition }: Props = $props();

	let bars = $derived(
		hasCompositionBar(composition) ? compositionSegments(composition!.species) : []
	);

	// The gases the trace segment stands for, biggest first — named in its
	// tooltip so the bucket isn't a dead end.
	let traceMembers = $derived.by(() => {
		const shown = new Set(bars.map((s) => s.key));
		return (composition?.species ?? [])
			.filter((s) => !shown.has(s.formula))
			.sort((a, b) => b.share - a.share);
	});

	// Column and number densities are per-species measurements taken at
	// different times and geometries, not a mixing ratio. Too load-bearing to
	// hide behind a hover, so it rides under the legend as a caption.
	let compositionNote = $derived.by(() => {
		switch (composition?.unit) {
			case 'column_density':
			case 'number_density':
				return m.atmosphere_composition_relative_density();
			case 'mass_fraction':
				return m.atmosphere_composition_by_mass();
			default:
				return null;
		}
	});

	function segmentLabel(segment: {
		key: string;
		formula: string | null;
		share: number;
		limit: boolean;
	}): string {
		const name = segment.formula === null ? m.atmosphere_trace_full() : speciesName(segment.key);
		const value = formatPercent(segment.share);
		return segment.limit
			? m.atmosphere_species_limit({ name, value })
			: m.atmosphere_species_value({ name, value });
	}

	// Every species here is a formula, so every one has a name to reveal; the
	// trace bucket also lists what it stands for.
	let segments: CompositionSegment[] = $derived(
		bars.map((segment) => ({
			key: segment.key,
			label: segment.formula ?? m.atmosphere_trace(),
			value: `${segment.limit ? '<' : ''}${formatPercent(segment.share)}`,
			tooltip: segmentLabel(segment),
			share: segment.share,
			color: segment.color,
			limit: segment.limit,
			labelIsAbbreviated: true
		}))
	);
</script>

{#snippet detail(segment: CompositionSegment)}
	{#if segment.key === '__trace__' && traceMembers.length}
		<dl class="mt-1 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 leading-snug opacity-70">
			{#each traceMembers as gas (gas.formula)}
				<dt>{speciesName(gas.formula)}</dt>
				<!-- One significant digit: trace members run down to parts per billion,
				     where a fixed digit count rounds everything to zero. -->
				<dd class="text-end tabular-nums">{formatPercent(gas.share, 1)}</dd>
			{/each}
		</dl>
	{/if}
{/snippet}

<CompositionBar {segments} {detail} caption={compositionNote} />
