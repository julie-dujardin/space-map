<script lang="ts">
	/**
	 * The Structure tab: the atmosphere first, then the interior under it, top
	 * down. The two charts have their own scales, because Earth's mantle is
	 * 2,900 km thick and its drawn atmosphere 85 km. The interior chart of a
	 * giant or the Sun has no atmosphere strip, because its outer layer is its
	 * atmosphere.
	 *
	 * The atmosphere section also holds the composition bar of the Overview. The
	 * bar shows where the stack has nothing to draw.
	 *
	 * A temperature belongs to a layer. There is no core temperature row:
	 * geotherms are published at boundaries, and most boundaries have none.
	 *
	 * Each section gives its values first, then the drawing. The layer cards
	 * follow the cutaway as its legend.
	 *
	 * A star other than the Sun has no bundle block. Its panel passes the block
	 * built from its Interior row, its effective temperature and its own rows.
	 */
	import type { Snippet } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import type {
		GlobalObjectData,
		InteriorBlock,
		LocalizedObjectData
	} from '$lib/fetch/objects/object-data';
	import { crossSection, layerRows, type InteriorBand } from '$lib/charts/interior-cross-section';
	import { atmosphereProfile, drawableTopKm } from '$lib/charts/atmosphere-cross-section';
	import { atmosphereNoteBesideChart, atmosphereTypeName } from '$lib/charts/atmosphere-layers';
	import {
		bandColor,
		coreBracket,
		layerSpans,
		skyRgb,
		type PlasmaRange
	} from '$lib/charts/layer-appearance';
	import { ucfirst } from '$lib/format/quantities';
	import Section from './kit/Section.svelte';
	import Surface from './Surface.svelte';
	import Row from './kit/Row.svelte';
	import TopicSummary from './kit/TopicSummary.svelte';
	import AtmosphereComposition, { hasCompositionBar } from './kit/AtmosphereComposition.svelte';
	import MassDensityRows from './kit/MassDensityRows.svelte';
	import InteriorCrossSection from '../charts/InteriorCrossSection.svelte';
	import AtmosphereCrossSection from '../charts/AtmosphereCrossSection.svelte';
	import LayerCard from '../charts/LayerCard.svelte';
	import Activity from './Activity.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		/** In place of the bundle's block: a star's, from its Interior row. */
		interior?: InteriorBlock;
		/** In place of the bundle's readings: a star's effective temperature, K. */
		surfaceK?: number | null;
		/** Shading anchors where the star has no reading for one end. For the
		 *  picture only, as the ramp is. */
		nominalPlasma?: PlasmaRange;
		/** In place of the mass and activity rows above the cutaway. */
		rows?: Snippet;
	}

	let {
		global,
		localized,
		interior: interiorOverride,
		surfaceK: surfaceOverride,
		nominalPlasma,
		rows: interiorRows
	}: Props = $props();

	let interior = $derived(interiorOverride ?? global?.interior);
	let layers = $derived(interior?.layers ?? []);
	let structure = $derived(global?.atmosphere?.structure);
	let active = $state<number | null>(null);

	// "fluid" is the giants and the Sun — no solid surface, so no boundary
	// between the body and its air, so nothing to draw a separate strip against.
	let hasOwnAtmosphere = $derived(interior?.structure === 'fluid');
	let atmosphereKm = $derived(structure ? (drawableTopKm(structure) ?? undefined) : undefined);
	let section = $derived(crossSection(layers, { atmosphereKm, hasOwnAtmosphere }));

	// Layers sharing a depth but not a place lay out across, not down: Earth's
	// two crusts meet at a coastline, and stacking them would say the basalt is
	// buried in the granite. Equal columns, not columns sized by area — each
	// card carries the same weight of numbers either way.
	let rows = $derived(section ? layerRows(section.bands) : []);
	let index = $derived(new Map(section?.bands.map((band, i) => [band, i]) ?? []));

	// Callisto is the only miss: an exosphere nobody has put a top on has no
	// bands to draw. The section still shows for its composition bar.
	let profile = $derived(structure ? atmosphereProfile(structure) : null);
	let hasChart = $derived(!!profile?.bands.length);

	let composition = $derived(global?.atmosphere?.composition);
	let hasBar = $derived(hasCompositionBar(composition));

	let note = $derived(atmosphereNoteBesideChart(global?.atmosphere?.note));
	let type = $derived(
		global?.atmosphere ? ucfirst(atmosphereTypeName(global.atmosphere.type)) : null
	);

	let readings = $derived(global?.temperatures?.readings ?? []);

	let core = $derived(coreBracket(readings));

	/** What the outside of the body is at. The Sun quotes its photosphere where
	 *  everything else quotes a surface. */
	let surfaceK = $derived.by(() => {
		if (surfaceOverride !== undefined) return surfaceOverride;
		const value =
			readings.find((r) => r.part === 'surface' && r.kind === 'mean') ??
			readings.find((r) => r.part === 'photosphere' && r.kind === 'mean');
		return value?.k ?? null;
	});

	/** The centre, where a body publishes one — the Sun and the giants, whose
	 *  dilute cores have no radius to hang a boundary on. */
	let centre = $derived.by(() => {
		if (interior?.centre_temperature_range_k) {
			const [lowK, highK] = interior.centre_temperature_range_k;
			return { lowK, highK };
		}
		const value = interior?.centre_temperature_k;
		return value !== undefined ? { lowK: value, highK: value } : null;
	});

	let layerTemperatures = $derived(layerSpans(layers, centre, surfaceK));

	// A star's zones sit between its centre and its surface with no boundary of
	// their own; the two ends anchor a ramp used for shading and nothing else.
	let plasmaRange = $derived.by(() => {
		if (!layers.some((l) => l.state === 'plasma')) return undefined;
		const inner = core ?? centre;
		const innerK = inner ? (inner.lowK + inner.highK) / 2 : nominalPlasma?.innerK;
		const outerK = surfaceK ?? nominalPlasma?.outerK;
		if (innerK === undefined || outerK === undefined) return undefined;
		return { innerK, outerK };
	});

	// What the sky would look like, read off what the air is made of — the same
	// treatment the cutaway gets, and not the categorical hue the composition
	// bar uses to tell one gas from another.
	let gasColor = $derived(skyRgb(global?.atmosphere?.composition?.species));

	let activity = $derived(global?.activity);
</script>

{#if hasChart || hasBar}
	<Section title={m.structure_atmosphere()}>
		<!-- "Atmosphere of X", where this locale has it. The tab is otherwise
		     charts and numbers end to end, so this is the only place a reader is
		     told in words what they are looking at, and it opens the section. -->
		{#snippet header()}
			<TopicSummary page={localized?.atmosphere_page} />
		{/snippet}
		<!-- What kind of atmosphere, then what the drawing can't show: that the
		     envelope comes and goes (Mars freezes a quarter of its air onto the
		     winter cap). The interior gets no such line — a layer's caveats live
		     on its own card instead. -->
		{#if type}
			<Row label={m.atmosphere_classification()} value={type} />
		{/if}
		{#if note}
			<dd class="text-muted-foreground col-span-2 -mt-1.5 text-[11px] leading-snug">{note}</dd>
		{/if}
		{#snippet footer()}
			{#if profile && profile.bands.length}
				<AtmosphereCrossSection {profile} color={gasColor} />
			{/if}
			<AtmosphereComposition {composition} />
		{/snippet}
	</Section>
{/if}

<!-- Between the two cross-sections because that is where it sits physically:
     the air ends, the surface is the reading taken on it, and the interior
     starts below. Renders itself away on a body with nothing to say, so
     whether this tab exists at all is still decided upstream. -->
<Surface {global} />

<!-- Declared out here rather than inside `Section`: a snippet in a component's
     markup is one of its props. -->
{#snippet card(band: InteriorBand)}
	{@const i = index.get(band) ?? 0}
	<LayerCard
		{band}
		swatch={bandColor(band, layerTemperatures[i], plasmaRange)}
		temperature={layerTemperatures[i]}
		outermost={i === 0}
		dimmed={active !== null && active !== i}
		onenter={() => (active = i)}
		onleave={() => (active = null)}
	/>
{/snippet}

{#if section}
	<Section title={m.structure_interior()}>
		{#snippet header()}
			<TopicSummary page={localized?.interior_page} />
		{/snippet}
		<!-- Above the cutaway, on the section's own `dl`: these are numbers about
		     the whole body, and the drawing is the thing they are about. The layer
		     cards stay directly under it as its legend. -->
		{#if interiorRows}
			{@render interiorRows()}
		{:else}
			<MassDensityRows {global} />
			{#if activity}
				<Activity {activity} />
			{/if}
		{/if}
		{#snippet footer()}
			<InteriorCrossSection
				{section}
				atmosphereColor={gasColor}
				temperatures={layerTemperatures}
				{plasmaRange}
				datum={structure?.datum}
				bind:active
			/>
			{#each rows as row, r (row[0].layer.role + r)}
				{#if row.length > 1}
					<div
						class="grid gap-x-3"
						style="grid-template-columns: repeat({row.length}, minmax(0, 1fr))"
					>
						{#each row as band (band.layer.role)}
							{@render card(band)}
						{/each}
					</div>
				{:else}
					{@render card(row[0])}
				{/if}
			{/each}
		{/snippet}
	</Section>
{:else if activity}
	<!-- Nothing takes this branch today — every body in the activity block has a
	     layer model, and a constants test holds that. It stands for the one that
	     does not: a volcanic record with no resolved interior would otherwise
	     have nowhere on this tab to land. -->
	<Section title={m.activity()}>
		<Activity {activity} />
	</Section>
{/if}
