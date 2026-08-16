<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type { AppState } from '$lib/state/app-state.svelte';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { materialEntries } from '$lib/charts/interior-materials';
	import { coreBracket } from '$lib/charts/layer-appearance';
	import { structureLink } from '$lib/charts/structure-link';
	import { isModifiedClick, tabHref } from '$lib/state/focus-link';
	import type { CompositionEntry } from '$lib/charts/composition-bar';
	import { formatKelvinRange } from '$lib/format/temperature';
	import { ucfirst } from '$lib/format/quantities';
	import { activitySummary, fieldSummary } from '$lib/format/activity';
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

	// Nobody has measured a planetary core, so this is a low-high bracket of
	// model spread, not a value with an error bar — shown off the temperature
	// scale that draws the outside of the body (millions of K apart on the Sun).
	let coreTemperature = $derived.by(() => {
		const bracket = coreBracket(global?.temperatures?.readings ?? []);
		return bracket ? formatKelvinRange(bracket.lowK, bracket.highK) : null;
	});

	const appState = getContext<AppState>('appState');

	let interior = $derived(global?.interior);
	// The panel's one caveat line: only the ocean arrives as a `note` key, the
	// rest derive from fields already on show whose one-word labels need a
	// sentence to unpack.
	let note = $derived.by(() => {
		if (!interior) return null;
		if (interior.note === 'subsurface_ocean') return m.interior_note_subsurface_ocean();
		if (interior.estimated) return m.interior_note_taxonomy_estimate();
		if (interior.structure === 'rubble_pile') return m.interior_note_rubble_pile();
		return null;
	});
	let link = $derived(structureLink(global));
	let structureHref = $derived(link ? tabHref(appState, 'structure') : undefined);
	let linkLabel = $derived(link?.layers ? m.structure_see_layers() : m.structure_see_more());

	function openStructure(e: MouseEvent) {
		if (isModifiedClick(e)) return;
		e.preventDefault();
		appState.setTab('structure');
	}

	let entries: CompositionEntry[] = $derived(
		interior?.composition ? materialEntries(interior.composition) : []
	);

	// Two rows, both categorical, since most bodies here have a status but few
	// measurements (those live on the Structure tab). Kept orthogonal rather
	// than merged — Jupiter has a field and no tide, Mimas the reverse.
	let activity = $derived(activitySummary(global?.activity));
	let field = $derived(fieldSummary(global?.activity?.magnetism));
</script>

{#if interior || coreTemperature || activity || field}
	<Section
		title={m.interior()}
		activateHref={structureHref}
		onActivate={openStructure}
		activateLabel={linkLabel}
	>
		{#snippet header()}
			<CompositionBar {entries} />
		{/snippet}

		{#if interior?.structure}
			<Row
				label={m.interior_structure()}
				value={ucfirst(STRUCTURE_LABEL[interior.structure]?.() ?? interior.structure)}
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
				value={ucfirst(ANALOGUE[interior.analogue]?.() ?? interior.analogue)}
			/>
		{/if}
		{#if coreTemperature}
			<Row label={m.temperature_of_core()}>
				<span class="tabular-nums">{coreTemperature}</span>
			</Row>
		{/if}
		{#if activity}
			<Row label={m.activity()} value={activity} />
		{/if}
		{#if field}
			<Row label={m.activity_magnetic_field()} value={field} />
		{/if}
		{#if note}
			<dd class="text-muted-foreground col-span-2 -mt-1.5 text-[11px] leading-snug">{note}</dd>
		{/if}
	</Section>
{/if}
