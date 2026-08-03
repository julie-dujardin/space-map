<script lang="ts">
	/**
	 * The Structure tab: the body cut open, then the air above it.
	 *
	 * Two charts rather than one because the scales cannot be shared — Earth's
	 * mantle is 2,900 km against 85 km of drawable atmosphere. The giants and
	 * the Sun get only the first: their outermost layer already *is* their
	 * atmosphere, and a strip on top of it would draw the same gas twice.
	 *
	 * Temperature is attached per layer rather than shown as one "core
	 * temperature" row, but only where a reading exists: bodies carry a modelled
	 * core bracket and a measured surface value, and nothing for the mantles in
	 * between. A layer with no number shows none.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { crossSection, type InteriorBand } from '$lib/charts/interior-cross-section';
	import { drawableTopKm } from '$lib/charts/atmosphere-cross-section';
	import { interiorLayerRgb, plasmaRgb, skyRgb } from '$lib/charts/layer-appearance';
	import { formatQuantity } from '$lib/format/quantities';
	import { ltrIsolate } from '$lib/format/bidi';
	import Section from './kit/Section.svelte';
	import InteriorCrossSection from '../charts/InteriorCrossSection.svelte';
	import AtmosphereCrossSection from '../charts/AtmosphereCrossSection.svelte';
	import LayerCard from '../charts/LayerCard.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let layers = $derived(global?.interior?.layers ?? []);
	let structure = $derived(global?.atmosphere?.structure);
	let active = $state<number | null>(null);

	// "fluid" is the giants and the Sun — no solid surface, so no boundary
	// between the body and its air, so nothing to draw a separate strip against.
	let hasOwnAtmosphere = $derived(global?.interior?.structure === 'fluid');
	let atmosphereKm = $derived(structure ? (drawableTopKm(structure) ?? undefined) : undefined);
	let section = $derived(crossSection(layers, { atmosphereKm, hasOwnAtmosphere }));

	let readings = $derived(global?.temperatures?.readings ?? []);

	/** The modelled bracket, which belongs to the core and to nothing else. */
	let coreBracket = $derived.by(() => {
		const low = readings.find((r) => r.part === 'core' && r.kind === 'min');
		const high = readings.find((r) => r.part === 'core' && r.kind === 'max');
		return low && high ? { lowK: low.k, highK: high.k } : null;
	});

	/** What the outside of the body is at. The Sun quotes its photosphere where
	 *  everything else quotes a surface. */
	let outerReading = $derived.by(() => {
		const value =
			readings.find((r) => r.part === 'surface' && r.kind === 'mean') ??
			readings.find((r) => r.part === 'photosphere' && r.kind === 'mean');
		return value ? { lowK: value.k, highK: value.k } : null;
	});

	const CORE_ROLES = new Set(['core', 'inner_core', 'outer_core']);

	// Only the two ends of the body have a reading. Everything between them —
	// every mantle, every ice shell — has none, and gets none.
	let layerTemperatures = $derived(
		layers.map((layer, i) => {
			if (CORE_ROLES.has(layer.role)) return coreBracket;
			if (i === 0) return outerReading;
			return null;
		})
	);

	let temperatureK = $derived(layerTemperatures.map((t) => (t ? (t.lowK + t.highK) / 2 : null)));

	// A star's zones sit between its core and its surface with no reading of
	// their own; the two ends anchor a ramp used for shading and nothing else.
	let plasmaRange = $derived.by(() => {
		if (!layers.some((l) => l.state === 'plasma')) return undefined;
		if (!coreBracket || !outerReading) return undefined;
		return { innerK: (coreBracket.lowK + coreBracket.highK) / 2, outerK: outerReading.lowK };
	});

	function swatch(band: InteriorBand, i: number): string {
		if (band.layer.state === 'plasma' && plasmaRange && temperatureK[i] == null) {
			return plasmaRgb((band.outer + band.inner) / 2, plasmaRange.innerK, plasmaRange.outerK);
		}
		return interiorLayerRgb(band.layer, temperatureK[i], 1 - (band.outer + band.inner) / 2);
	}

	// What the sky would look like, read off what the air is made of — the same
	// treatment the cutaway gets, and not the categorical hue the composition
	// bar uses to tell one gas from another.
	let gasColor = $derived(skyRgb(global?.atmosphere?.composition?.species));

	let interiorMeta = $derived(
		section
			? m.structure_to_scale_radius({
					value: ltrIsolate(formatQuantity({ value: section.radiusKm, unit: 'kilometre' }, true))
				})
			: undefined
	);
	let atmosphereMeta = $derived(
		atmosphereKm
			? m.structure_to_scale({
					value: ltrIsolate(formatQuantity({ value: atmosphereKm, unit: 'kilometre' }, true))
				})
			: undefined
	);
</script>

{#if section}
	<Section title={m.structure_interior()} meta={interiorMeta}>
		{#snippet header()}
			<InteriorCrossSection
				{layers}
				{atmosphereKm}
				{hasOwnAtmosphere}
				temperatures={layerTemperatures}
				{plasmaRange}
				bind:active
			/>
		{/snippet}
		{#snippet footer()}
			{#each section.bands as band, i (band.layer.role + i)}
				<LayerCard
					{band}
					swatch={swatch(band, i)}
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

{#if structure}
	<Section title={m.structure_atmosphere()} meta={atmosphereMeta}>
		{#snippet header()}
			<AtmosphereCrossSection {structure} color={gasColor} />
		{/snippet}
	</Section>
{/if}
