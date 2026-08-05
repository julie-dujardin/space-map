<script lang="ts">
	/**
	 * The Structure tab: the air first, then the body cut open under it — the
	 * page reads top-down the way the body stacks.
	 *
	 * Two charts rather than one because the scales cannot be shared — Earth's
	 * mantle is 2,900 km against 85 km of drawable atmosphere. The giants and
	 * the Sun get only the first: their outermost layer already *is* their
	 * atmosphere, and a strip on top of it would draw the same gas twice.
	 *
	 * The atmosphere section also carries the Overview's composition bar, and
	 * shows for it even where the vertical stack has nothing to draw.
	 *
	 * Temperature is attached per layer rather than shown as one "core
	 * temperature" row, and comes from the layer's two boundaries: geotherms are
	 * published at the Moho, at the core-mantle boundary, at the centre, never
	 * as an average over a shell. Most boundaries have no published number and
	 * the layer then shows none.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { crossSection } from '$lib/charts/interior-cross-section';
	import { atmosphereProfile, drawableTopKm } from '$lib/charts/atmosphere-cross-section';
	import { atmosphereNoteBesideChart, atmosphereTypeName } from '$lib/charts/atmosphere-layers';
	import { bandColor, coreBracket, layerSpans, skyRgb } from '$lib/charts/layer-appearance';
	import { formatKm } from '$lib/format/distance';
	import { ltrIsolate } from '$lib/format/bidi';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import TopicSummary from './kit/TopicSummary.svelte';
	import AtmosphereComposition, { hasCompositionBar } from './kit/AtmosphereComposition.svelte';
	import InteriorCrossSection from '../charts/InteriorCrossSection.svelte';
	import AtmosphereCrossSection from '../charts/AtmosphereCrossSection.svelte';
	import LayerCard from '../charts/LayerCard.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
	}

	let { global, localized }: Props = $props();

	let layers = $derived(global?.interior?.layers ?? []);
	let structure = $derived(global?.atmosphere?.structure);
	let active = $state<number | null>(null);

	// "fluid" is the giants and the Sun — no solid surface, so no boundary
	// between the body and its air, so nothing to draw a separate strip against.
	let hasOwnAtmosphere = $derived(global?.interior?.structure === 'fluid');
	let atmosphereKm = $derived(structure ? (drawableTopKm(structure) ?? undefined) : undefined);
	let section = $derived(crossSection(layers, { atmosphereKm, hasOwnAtmosphere }));

	// Callisto is the only miss: an exosphere nobody has put a top on has no
	// bands to draw. The section still shows for its composition bar.
	let profile = $derived(structure ? atmosphereProfile(structure) : null);
	let hasChart = $derived(!!profile?.bands.length);

	let composition = $derived(global?.atmosphere?.composition);
	let hasBar = $derived(hasCompositionBar(composition));

	let note = $derived(atmosphereNoteBesideChart(global?.atmosphere?.note));
	let type = $derived(global?.atmosphere ? atmosphereTypeName(global.atmosphere.type) : null);

	let readings = $derived(global?.temperatures?.readings ?? []);

	let core = $derived(coreBracket(readings));

	/** What the outside of the body is at. The Sun quotes its photosphere where
	 *  everything else quotes a surface. */
	let surfaceK = $derived.by(() => {
		const value =
			readings.find((r) => r.part === 'surface' && r.kind === 'mean') ??
			readings.find((r) => r.part === 'photosphere' && r.kind === 'mean');
		return value?.k ?? null;
	});

	/** The centre, where a body publishes one — the Sun and the giants, whose
	 *  dilute cores have no radius to hang a boundary on. */
	let centre = $derived.by(() => {
		const interior = global?.interior;
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
		if (!core || surfaceK === null) return undefined;
		return { innerK: (core.lowK + core.highK) / 2, outerK: surfaceK };
	});

	// What the sky would look like, read off what the air is made of — the same
	// treatment the cutaway gets, and not the categorical hue the composition
	// bar uses to tell one gas from another.
	let gasColor = $derived(skyRgb(global?.atmosphere?.composition?.species));

	let interiorMeta = $derived(
		section
			? m.structure_to_scale_radius({ value: ltrIsolate(formatKm(section.radiusKm)) })
			: undefined
	);
	let atmosphereMeta = $derived(
		atmosphereKm ? m.structure_to_scale({ value: ltrIsolate(formatKm(atmosphereKm)) }) : undefined
	);
</script>

{#if hasChart || hasBar}
	<Section title={m.structure_atmosphere()} meta={atmosphereMeta}>
		<!-- "Atmosphere of X", where this locale has it. The tab is otherwise
		     charts and numbers end to end, so this is the only place a reader is
		     told in words what they are looking at, and it opens the section. -->
		{#snippet header()}
			<TopicSummary page={localized?.atmosphere_page} />
		{/snippet}
		<!-- What kind of atmosphere this is, then what the drawing cannot show:
		     that the whole envelope comes and goes. Mars freezes a quarter of its
		     air onto the winter cap, and the stack below is the half of the year
		     it is in the air. The interior gets no such line — a layer's caveats
		     are on its own card under the disc. -->
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

{#if section}
	<Section title={m.structure_interior()} meta={interiorMeta}>
		{#snippet header()}
			<TopicSummary page={localized?.interior_page} />
			<InteriorCrossSection
				{section}
				atmosphereColor={gasColor}
				temperatures={layerTemperatures}
				{plasmaRange}
				datum={structure?.datum}
				bind:active
			/>
		{/snippet}
		{#snippet footer()}
			{#each section.bands as band, i (band.layer.role + i)}
				<LayerCard
					{band}
					swatch={bandColor(band, layerTemperatures[i], plasmaRange)}
					temperature={layerTemperatures[i]}
					outermost={i === 0}
					dimmed={active !== null && active !== i}
					onenter={() => (active = i)}
					onleave={() => (active = null)}
				/>
			{/each}
		{/snippet}
	</Section>
{/if}
