<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { compositionSegments, speciesName } from '$lib/charts/atmosphere-species';
	import type { CompositionSegment } from '$lib/charts/composition-bar';
	import { formatPressure, EARTH_SEA_LEVEL_PA, formatEarthRatio } from '$lib/format/pressure';
	import { ltrIsolate } from '$lib/format/bidi';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import CompositionBar from './kit/CompositionBar.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	const TYPE_LABEL: Record<string, () => string> = {
		exosphere: m.atmosphere_type_exosphere,
		tenuous_exosphere: m.atmosphere_type_tenuous_exosphere,
		transient_exosphere: m.atmosphere_type_transient_exosphere,
		tenuous_collisional: m.atmosphere_type_tenuous_collisional,
		thin_atmosphere: m.atmosphere_type_thin_atmosphere,
		thick_atmosphere: m.atmosphere_type_thick_atmosphere,
		gas_giant_envelope: m.atmosphere_type_gas_giant_envelope,
		stellar_atmosphere: m.atmosphere_type_stellar_atmosphere,
		localized_plume: m.atmosphere_type_localized_plume,
		frozen_collapsed: m.atmosphere_type_frozen_collapsed,
		none_detected: m.atmosphere_type_none_detected
	};

	const LEVEL_LABEL: Record<string, () => string> = {
		surface: m.atmosphere_pressure_surface,
		sea_level: m.atmosphere_pressure_sea_level,
		areoid: m.atmosphere_pressure_areoid,
		cloud_top: m.atmosphere_pressure_cloud_top,
		one_bar: m.atmosphere_pressure_one_bar,
		photosphere: m.atmosphere_pressure_photosphere
	};

	// What keeps this atmosphere the way it is — the half the classification
	// leaves unsaid, and the reason a pressure can be "variable".
	const NOTE: Record<string, () => string> = {
		photosphere: m.atmosphere_note_photosphere,
		surface_bounded: m.atmosphere_note_surface_bounded,
		sputtered_ice: m.atmosphere_note_sputtered_ice,
		volcanic: m.atmosphere_note_volcanic,
		seasonal_cap: m.atmosphere_note_seasonal_cap,
		seasonal_orbit: m.atmosphere_note_seasonal_orbit,
		frozen_out: m.atmosphere_note_frozen_out,
		no_detection: m.atmosphere_note_no_detection,
		plume: m.atmosphere_note_plume,
		transient_vapour: m.atmosphere_note_transient_vapour,
		no_surface: m.atmosphere_note_no_surface
	};

	let atmosphere = $derived(global?.atmosphere);
	let pressure = $derived(atmosphere?.pressure);
	let note = $derived(atmosphere?.note ? (NOTE[atmosphere.note]?.() ?? null) : null);

	// Everything the bar shows is a share of the species we list, so a body
	// whose sources only pin one gas is a full bar of that gas — true, but it
	// reads as a measurement it isn't. Two species minimum.
	let bars = $derived(
		atmosphere?.composition && atmosphere.composition.species.length > 1
			? compositionSegments(atmosphere.composition.species)
			: []
	);

	// The gases the trace segment stands for, biggest first — named in its
	// tooltip so the bucket isn't a dead end.
	let traceMembers = $derived.by(() => {
		const shown = new Set(bars.map((s) => s.key));
		return (atmosphere?.composition?.species ?? [])
			.filter((s) => !shown.has(s.formula))
			.sort((a, b) => b.share - a.share);
	});

	// Column and number densities are per-species measurements taken at
	// different times and geometries, not a mixing ratio. Too load-bearing to
	// hide behind a hover, so it rides under the legend as a caption.
	let compositionNote = $derived.by(() => {
		switch (atmosphere?.composition?.unit) {
			case 'column_density':
			case 'number_density':
				return m.atmosphere_composition_relative_density();
			case 'mass_fraction':
				return m.atmosphere_composition_by_mass();
			default:
				return null;
		}
	});

	let percent = $derived(
		new Intl.NumberFormat(getLocale(), { style: 'percent', maximumSignificantDigits: 2 })
	);
	// Trace members run down to parts per billion, where a percentage with a
	// fixed digit count rounds everything to zero.
	let traceShare = $derived(
		new Intl.NumberFormat(getLocale(), { style: 'percent', maximumSignificantDigits: 1 })
	);

	// Sixteen orders of magnitude of pressure mean nothing on their own; Earth
	// is the ruler everyone carries. Skipped on Earth, where it would read
	// "100% of Earth".
	let earthRatio = $derived(
		pressure && Math.abs(pressure.pa - EARTH_SEA_LEVEL_PA) > 1
			? formatEarthRatio(pressure.pa)
			: null
	);

	function segmentLabel(segment: {
		key: string;
		formula: string | null;
		share: number;
		limit: boolean;
	}): string {
		const name = segment.formula === null ? m.atmosphere_trace_full() : speciesName(segment.key);
		const value = percent.format(segment.share);
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
			value: `${segment.limit ? '<' : ''}${percent.format(segment.share)}`,
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
				<dd class="text-end tabular-nums">{traceShare.format(gas.share)}</dd>
			{/each}
		</dl>
	{/if}
{/snippet}

{#if atmosphere}
	<Section title={m.atmosphere()}>
		{#snippet header()}
			<CompositionBar {segments} {detail} caption={compositionNote} />
		{/snippet}

		<Row
			label={m.atmosphere_classification()}
			value={TYPE_LABEL[atmosphere.type]?.() ?? atmosphere.type}
		/>
		{#if note}
			<dd class="text-muted-foreground col-span-2 -mt-1.5 text-[11px] leading-snug">{note}</dd>
		{/if}
		{#if pressure}
			{@const reading = ltrIsolate(
				`${pressure.qualifier === 'upper_limit' ? '<' : '≈'} ${formatPressure(pressure.pa)}`
			)}
			<Row label={LEVEL_LABEL[pressure.level]?.() ?? m.atmosphere_pressure_surface()}>
				{#if earthRatio}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<span
									class="cursor-help tabular-nums underline decoration-dotted underline-offset-2"
									{...props}>{reading}</span
								>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{earthRatio}</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					<span class="tabular-nums">{reading}</span>
				{/if}
			</Row>
		{/if}
	</Section>
{/if}
