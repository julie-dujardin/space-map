<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { compositionSegments } from '$lib/charts/interior-materials';
	import type { CompositionSegment } from '$lib/charts/composition-bar';
	import { formatTemperature } from '$lib/format/temperature';
	import { ltrIsolate } from '$lib/format/bidi';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import CompositionBar from './kit/CompositionBar.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	const STRUCTURE_LABEL: Record<string, () => string> = {
		differentiated: m.interior_structure_differentiated,
		partially_differentiated: m.interior_structure_partially_differentiated,
		undifferentiated: m.interior_structure_undifferentiated,
		rubble_pile: m.interior_structure_rubble_pile,
		fluid: m.interior_structure_fluid
	};

	// The caveat a material list can't carry on its own — why a core is only
	// an estimate, or that the water is locked in the rock rather than lying
	// on top of it.
	const NOTE: Record<string, () => string> = {
		subsurface_ocean: m.interior_note_subsurface_ocean,
		magma_ocean: m.interior_note_magma_ocean,
		no_seismic_data: m.interior_note_no_seismic_data,
		from_moment_of_inertia: m.interior_note_from_moment_of_inertia,
		from_bulk_density: m.interior_note_from_bulk_density,
		core_size_disputed: m.interior_note_core_size_disputed,
		rubble_pile: m.interior_note_rubble_pile,
		hydrated_rock: m.interior_note_hydrated_rock,
		no_solid_surface: m.interior_note_no_solid_surface,
		taxonomy_estimate: m.interior_note_taxonomy_estimate
	};

	const ANALOGUE: Record<string, () => string> = {
		ordinary_chondrite: m.interior_analogue_ordinary_chondrite,
		carbonaceous_chondrite: m.interior_analogue_carbonaceous_chondrite,
		hydrated_carbonaceous_chondrite: m.interior_analogue_hydrated_carbonaceous_chondrite,
		cv_co_chondrite: m.interior_analogue_cv_co_chondrite,
		hed_achondrite: m.interior_analogue_hed_achondrite,
		iron_with_silicate: m.interior_analogue_iron_with_silicate,
		aubrite: m.interior_analogue_aubrite,
		olivine_achondrite: m.interior_analogue_olivine_achondrite
	};

	// Nobody has measured a planetary core, so this arrives as a low-high
	// bracket of model spread rather than a value with an error bar. Shown as
	// the bracket, off the temperature scale that draws the outside of the body
	// — the two are millions of kelvin apart on the Sun.
	let coreTemperature = $derived.by(() => {
		const readings = global?.temperatures?.readings.filter((r) => r.part === 'core') ?? [];
		const low = readings.find((r) => r.kind === 'min');
		const high = readings.find((r) => r.kind === 'max');
		if (!low || !high) return null;
		const format = (k: number) => formatTemperature({ value: k, unit: 'kelvin' });
		return ltrIsolate(`${format(low.k)} – ${format(high.k)}`);
	});

	let interior = $derived(global?.interior);
	let note = $derived(interior?.note ? (NOTE[interior.note]?.() ?? null) : null);
	let percent = $derived(
		new Intl.NumberFormat(getLocale(), { style: 'percent', maximumSignificantDigits: 2 })
	);

	// The bar hovers everywhere — a coloured block says nothing on its own. The
	// legend only hovers where it shows a symbol: "H" needs spelling out,
	// "rock" does not.
	let segments: CompositionSegment[] = $derived(
		(interior?.composition ? compositionSegments(interior.composition) : []).map((segment) => ({
			key: segment.material,
			label: segment.symbol,
			value: percent.format(segment.share),
			tooltip: m.interior_material_value({
				name: segment.name,
				value: percent.format(segment.share)
			}),
			labelIsAbbreviated: segment.symbol !== segment.name,
			share: segment.share,
			color: segment.color
		}))
	);
</script>

{#if interior || coreTemperature}
	<Section title={m.interior()}>
		{#snippet header()}
			<CompositionBar {segments} />
		{/snippet}

		{#if interior?.structure}
			<Row
				label={m.interior_structure()}
				value={STRUCTURE_LABEL[interior.structure]?.() ?? interior.structure}
			/>
		{/if}
		{#if interior?.estimated && interior.taxonomy_class}
			{@const spectrum = m.interior_spectral_class({ value: interior.taxonomy_class })}
			<Row label={m.interior_estimated_from()}>
				{#if interior.taxonomy_scheme}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<span class="cursor-help underline decoration-dotted underline-offset-2" {...props}>
									{spectrum}
								</span>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{interior.taxonomy_scheme}</Tooltip.Content>
					</Tooltip.Root>
				{:else}
					<span>{spectrum}</span>
				{/if}
			</Row>
		{/if}
		{#if interior?.analogue}
			<Row
				label={m.interior_analogue()}
				value={ANALOGUE[interior.analogue]?.() ?? interior.analogue}
			/>
		{/if}
		{#if coreTemperature}
			<Row label={m.temperature_of_core()} tooltip={m.tooltip_core_temperature_modelled()}>
				<span class="tabular-nums">{coreTemperature}</span>
			</Row>
		{/if}
		{#if note}
			<dd class="text-muted-foreground col-span-2 -mt-1.5 text-[11px] leading-snug">{note}</dd>
		{/if}
	</Section>
{/if}
