<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { materialSegments } from '$lib/charts/interior-materials';
	import { coreBracket } from '$lib/charts/layer-appearance';
	import { structureLink } from '$lib/charts/structure-link';
	import type { CompositionSegment } from '$lib/charts/composition-bar';
	import { formatKelvinRange } from '$lib/format/temperature';
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
		const bracket = coreBracket(global?.temperatures?.readings ?? []);
		return bracket ? formatKelvinRange(bracket.lowK, bracket.highK) : null;
	});

	const appState = getContext<AppState>('appState');

	let interior = $derived(global?.interior);
	// The panel's one caveat line. Only the ocean arrives as a `note` key — the
	// rest of that vocabulary is provenance metadata — while the others derive
	// from fields already on show, whose one-word labels ("rubble pile") need a
	// sentence to unpack.
	let note = $derived.by(() => {
		if (!interior) return null;
		if (interior.note === 'subsurface_ocean') return m.interior_note_subsurface_ocean();
		if (interior.estimated) return m.interior_note_taxonomy_estimate();
		if (interior.structure === 'rubble_pile') return m.interior_note_rubble_pile();
		if (interior.structure === 'fluid') return m.interior_note_no_solid_surface();
		return null;
	});
	let link = $derived(structureLink(global));
	let openStructure = $derived(link ? () => appState.setTab('structure') : undefined);
	let linkLabel = $derived(link?.layers ? m.structure_see_layers() : m.structure_see_more());

	let segments: CompositionSegment[] = $derived(
		interior?.composition ? materialSegments(interior.composition) : []
	);
</script>

{#if interior || coreTemperature}
	<Section title={m.interior()} onActivate={openStructure} activateLabel={linkLabel}>
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
			<Row label={m.temperature_of_core()}>
				<span class="tabular-nums">{coreTemperature}</span>
			</Row>
		{/if}
		{#if note}
			<dd class="text-muted-foreground col-span-2 -mt-1.5 text-[11px] leading-snug">{note}</dd>
		{/if}
	</Section>
{/if}
