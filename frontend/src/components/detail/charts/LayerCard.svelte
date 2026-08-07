<script lang="ts">
	/**
	 * One interior layer in full: what it is, how thick, how deep, how hot, and
	 * what it is made of.
	 *
	 * The bar is the same `CompositionBar` the Overview draws, over the same
	 * palette — a layer's rock has to be the colour the body's rock is, or the
	 * two panels are describing different planets.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { InteriorLayer } from '$lib/fetch/objects/object-data';
	import type { InteriorBand } from '$lib/charts/interior-cross-section';
	import type { CompositionEntry } from '$lib/charts/composition-bar';
	import type { TemperatureBracket } from '$lib/charts/layer-appearance';
	import { layerName, phaseName, rockName, stateName } from '$lib/charts/interior-layers';
	import { materialEntries, detailEntries, materialName } from '$lib/charts/interior-materials';
	import { ucfirst } from '$lib/format/quantities';
	import { formatPercent } from '$lib/format/quantities';
	import { formatKm, formatKmRange } from '$lib/format/distance';
	import { formatKelvinRange } from '$lib/format/temperature';
	import { ltrIsolate } from '$lib/format/bidi';
	import CompositionBar from '../sections/kit/CompositionBar.svelte';

	interface Props {
		band: InteriorBand;
		/** The colour it has in the cutaway, so the two read as one thing. */
		swatch: string;
		/** Kelvin, where the body has a reading for this layer. Most mantles have
		 *  none and simply show nothing. */
		temperature?: TemperatureBracket | null;
		/** Another layer is hovered, so this one steps back. */
		dimmed?: boolean;
		/** Nothing sits above it — which changes what `diffuse` means. */
		outermost?: boolean;
		onenter?: () => void;
		onleave?: () => void;
	}

	let {
		band,
		swatch,
		temperature = null,
		dimmed = false,
		outermost = false,
		onenter,
		onleave
	}: Props = $props();

	let layer = $derived<InteriorLayer>(band.layer);

	// Chemistry first where the literature gives one: Mars's crust has an oxide
	// table and "rock 100%" says nothing next to it. Otherwise the coarse
	// material split, and a layer of one material draws no bar at all.
	let entries: CompositionEntry[] = $derived.by(() => {
		if (layer.detail) return detailEntries(layer.detail.entries);
		if (layer.composition.length > 1) return materialEntries(layer.composition);
		return [];
	});

	// What the layer is, in the words the data actually supports: the most
	// specific name it carries, then the depth. A rock or a named polymorph
	// stands in for the state-and-material phrase rather than joining it —
	// "basalt" already says solid rock and says which rock, "ice VI" already
	// says solid water and says which of the two solid-water layers this is.
	let descriptor = $derived.by(() => {
		const bits: string[] = [];
		const material = layer.composition[0];
		const named = layer.rock ? rockName(layer.rock) : layer.phase ? phaseName(layer.phase) : null;
		if (named) {
			bits.push(named);
		} else if (layer.state && material) {
			bits.push(`${stateName(layer.state)} ${materialName(material.material)}`);
		} else if (material) {
			bits.push(materialName(material.material));
		}
		bits.push(ltrIsolate(formatKmRange(band.depthFromKm, band.depthToKm)));
		// Sentence case: the state and material vocabularies are lowercase so they
		// can be composed ("solid rock"), and this is where the phrase starts a
		// line of its own.
		return ucfirst(bits.join(' · '));
	});

	let reading = $derived(
		temperature ? formatKelvinRange(temperature.lowK, temperature.highK) : null
	);

	/** Two significant digits, except where that would round a layer up to the
	 *  whole body: Tethys's ice shell is 99.942% of it and the 0.058% left is
	 *  the core sitting right underneath in the same list. */
	function massPercent(fraction: number): string {
		for (let digits = 2; digits < 6; digits++) {
			const text = formatPercent(fraction, digits);
			if (fraction >= 1 || !text.includes('100')) return text;
		}
		return formatPercent(fraction, 6);
	}

	/** The share of the body, with its published width where the source gives
	 *  one — Venus's core is 24% to 57% and a lone 39% reads as a measurement.
	 *
	 *  A width narrower than the rounding is dropped rather than printed: the
	 *  ocean is 0.0228% to 0.0234% of the Earth, which at the two significant
	 *  digits the rest of the panel uses comes out as "0.023% (0.023%–0.023%)"
	 *  — a bracket that says only that somebody had one. */
	let mass = $derived.by(() => {
		if (layer.mass_fraction === undefined) return null;
		const value = massPercent(layer.mass_fraction);
		const range = layer.mass_fraction_range;
		if (!range) return m.structure_layer_mass({ value });
		const [low, high] = range.map(massPercent);
		if (low === value && high === value) return m.structure_layer_mass({ value });
		return m.structure_layer_mass_range({ value, low, high });
	});

	/** How much of the globe it is under, on the layers that are patches rather
	 *  than shells. Without it the two crusts read as a stack — 41 km of granite
	 *  with 6 km of basalt somewhere inside it — instead of as the two halves of
	 *  a surface that meet at a coastline. */
	let coverage = $derived(
		layer.area_fraction === undefined
			? null
			: m.structure_layer_surface({ value: formatPercent(layer.area_fraction) })
	);

	// A diffuse layer with nothing above it is not fading into anything: it
	// is a body whose interior nobody has divided.
	let footnote = $derived(
		layer.diffuse
			? outermost
				? m.structure_layer_no_boundaries()
				: m.structure_layer_diffuse()
			: ''
	);
</script>

<div
	class="border-s-2 ps-2.5 transition-opacity"
	class:opacity-50={dimmed}
	style="border-color: {swatch}"
	onmouseenter={onenter}
	onmouseleave={onleave}
	role="presentation"
>
	<!-- Wrapping, because a card is not always the width of the panel: Earth's
	     two crusts share the row and "Continental crust · 41 km thick" does not
	     fit across 41% of it. -->
	<div class="flex flex-wrap items-baseline gap-x-2">
		<span class="flex-1 text-sm font-medium">{layerName(layer.role, layer.note)}</span>
		<span class="text-muted-foreground shrink-0 text-[11px] tabular-nums">
			{m.structure_layer_thick({
				value: ltrIsolate(formatKm(band.thicknessKm))
			})}
		</span>
	</div>

	<div class="text-muted-foreground flex items-baseline gap-2 text-[11px] leading-snug">
		<span class="flex-1">{descriptor}</span>
		{#if reading}
			<span class="shrink-0 tabular-nums">{reading}</span>
		{/if}
	</div>

	<CompositionBar {entries} />

	{#if mass || coverage || footnote}
		<div class="text-muted-foreground mt-1 text-[10px] leading-snug">
			{[mass, coverage, footnote].filter(Boolean).join(' · ')}
		</div>
	{/if}
</div>
