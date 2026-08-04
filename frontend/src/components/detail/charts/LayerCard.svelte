<script lang="ts">
	/**
	 * One interior layer in full: what it is, how thick, how deep, how hot, and
	 * what it is made of.
	 *
	 * The bar is the same `CompositionBar` the Overview draws, over the same
	 * palette and the same hover sentences — a layer's rock has to be the colour
	 * the body's rock is, or the two panels are describing different planets.
	 *
	 * It prefers the layer's own chemistry where the literature gives one: Mars's
	 * crust has an oxide table and "rock 100%" says nothing next to it. Where it
	 * does not, the coarse material split stands in, and a layer of one material
	 * draws no bar at all.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { InteriorLayer } from '$lib/fetch/objects/object-data';
	import type { InteriorBand } from '$lib/charts/interior-cross-section';
	import type { CompositionSegment } from '$lib/charts/composition-bar';
	import type { TemperatureBracket } from '$lib/charts/layer-appearance';
	import { layerName, stateName, layerNote } from '$lib/charts/interior-layers';
	import {
		materialSegments,
		materialName,
		detailSpeciesName,
		detailSpeciesColor
	} from '$lib/charts/interior-materials';
	import { formatFormula } from '$lib/charts/atmosphere-species';
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

	/** The published widths, by material, for the hover to add. */
	let spreads = $derived(
		new Map(
			layer.composition
				.filter((c) => c.share_range)
				.map((c) => [c.material, c.share_range as [number, number]])
		)
	);

	// Chemistry first: it is the finer statement, and it is only ever present
	// where somebody measured it. Species follow the atmosphere's convention —
	// formula on the bar, its own colour, the spelled-out name on hover.
	let segments: CompositionSegment[] = $derived.by(() => {
		if (layer.detail) {
			return layer.detail.entries.map((entry) => {
				const value = formatPercent(entry.fraction);
				return {
					key: entry.species,
					label: formatFormula(entry.species),
					value,
					tooltip: m.interior_material_value({
						name: detailSpeciesName(entry.species),
						value
					}),
					labelIsAbbreviated: true,
					share: entry.fraction,
					color: detailSpeciesColor(entry.species)
				};
			});
		}
		if (layer.composition.length > 1) return materialSegments(layer.composition);
		return [];
	});

	// What the layer is, in the words the data actually supports: its phase and
	// its dominant material, then the caveat the source attached.
	let descriptor = $derived.by(() => {
		const bits: string[] = [];
		const material = layer.composition[0];
		if (layer.state && material) {
			bits.push(`${stateName(layer.state)} ${materialName(material.material)}`);
		} else if (material) {
			bits.push(materialName(material.material));
		}
		bits.push(ltrIsolate(formatKmRange(band.depthFromKm, band.depthToKm)));
		return bits.join(' · ');
	});

	let reading = $derived(
		temperature ? formatKelvinRange(temperature.lowK, temperature.highK) : null
	);

	/** The share of the body, with its published width where the source gives
	 *  one — Venus's core is 24% to 57% and a lone 39% reads as a measurement. */
	let mass = $derived.by(() => {
		if (layer.mass_fraction === undefined) return null;
		const value = formatPercent(layer.mass_fraction);
		return layer.mass_fraction_range
			? m.structure_layer_mass_range({
					value,
					low: formatPercent(layer.mass_fraction_range[0]),
					high: formatPercent(layer.mass_fraction_range[1])
				})
			: m.structure_layer_mass({ value });
	});

	let footnote = $derived.by(() => {
		const bits: string[] = [];
		// A diffuse layer with nothing above it is not fading into anything: it
		// is a body whose interior nobody has divided.
		if (layer.diffuse) {
			bits.push(outermost ? m.structure_layer_no_boundaries() : m.structure_layer_diffuse());
		}
		if (layer.note) {
			const note = layerNote(layer.note);
			if (note) bits.push(note);
		}
		return bits.join(' · ');
	});
</script>

<!-- The width a source published around a share, added under the hover rather
     than beside the legend: it is the qualifier, not the number. -->
{#snippet spread(segment: CompositionSegment)}
	{@const range = spreads.get(segment.key)}
	{#if range}
		<span class="opacity-70">
			{m.structure_share_range({
				low: formatPercent(range[0]),
				high: formatPercent(range[1])
			})}
		</span>
	{/if}
{/snippet}

<div
	class="border-s-2 ps-2.5 transition-opacity"
	class:opacity-50={dimmed}
	style="border-color: {swatch}"
	onmouseenter={onenter}
	onmouseleave={onleave}
	role="presentation"
>
	<div class="flex items-baseline gap-2">
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

	<CompositionBar {segments} detail={spread} />

	{#if mass || footnote}
		<div class="text-muted-foreground mt-1 text-[10px] leading-snug">
			{#if mass}{mass}{footnote ? ' · ' : ''}{/if}{footnote}
		</div>
	{/if}
</div>
