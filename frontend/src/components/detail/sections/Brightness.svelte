<script lang="ts">
	/**
	 * How the body looks and how hot its outside is — everything measured at a
	 * surface, a cloud deck or a photosphere rather than deep inside.
	 *
	 * The temperature bar drops `core` readings: those are modelled central
	 * temperatures and belong to Interior, and a scale holding both would be
	 * useless anyway — the Sun's core runs 15.5 million K against a 5772 K
	 * photosphere.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatNumber } from '$lib/format/quantities';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import TemperatureScale from './kit/TemperatureScale.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let wd = $derived(global?.wikidata);
	let sbdb = $derived(global?.sbdb);

	// Physically-derived surface colour + how it was obtained, for the swatch +
	// TrueColorTools credit.
	const COLOUR_METHOD = {
		spectrum: m.colour_method_spectrum,
		photometry: m.colour_method_photometry,
		taxonomy: m.colour_method_taxonomy,
		albedo: m.colour_method_albedo
	};
	// Small bodies carry it under `sbdb`; moons top-level, when textureless
	let colourSource = $derived(
		sbdb ?? (global && !global.map_texture_available ? global : undefined)
	);
	let colour = $derived(colourSource?.color);
	let colourMethod = $derived(
		colourSource?.color_method ? COLOUR_METHOD[colourSource.color_method]() : null
	);

	let outsideTemperatures = $derived.by(() => {
		const temperatures = global?.temperatures;
		if (!temperatures) return null;
		const readings = temperatures.readings.filter((r) => r.part !== 'core');
		return readings.length ? { ...temperatures, readings } : null;
	});

	let hasContent = $derived(
		sbdb?.albedo ||
			outsideTemperatures != null ||
			wd?.absolute_magnitude != null ||
			sbdb?.H != null ||
			wd?.apparent_magnitude != null ||
			sbdb?.spec_B ||
			sbdb?.spec_T ||
			colour
	);
</script>

{#if hasContent}
	<Section title={m.brightness_and_temperature()}>
		{#if sbdb?.albedo}
			<Row label={m.albedo()} value={formatNumber(sbdb.albedo)} tooltip={m.tooltip_albedo()} />
		{/if}
		{#if wd?.absolute_magnitude != null}
			<Row
				label={m.property_name_absolute_magnitude()}
				value={formatNumber(wd.absolute_magnitude)}
				tooltip={m.tooltip_absolute_magnitude()}
			/>
		{:else if sbdb?.H != null}
			<Row
				label={m.absolute_magnitude_h()}
				value={formatNumber(sbdb.H)}
				tooltip={m.tooltip_absolute_magnitude_h()}
			/>
		{/if}
		{#if wd?.apparent_magnitude != null}
			<Row
				label={m.property_name_apparent_magnitude()}
				value={formatNumber(wd.apparent_magnitude)}
				tooltip={m.tooltip_apparent_magnitude()}
			/>
		{/if}
		{#if sbdb?.spec_B}
			<Row
				label={m.spectral_type_smassii()}
				value={sbdb.spec_B}
				tooltip={m.tooltip_spectral_type_smassii()}
			/>
		{/if}
		{#if sbdb?.spec_T}
			<Row
				label={m.spectral_type_tholen()}
				value={sbdb.spec_T}
				tooltip={m.tooltip_spectral_type_tholen()}
			/>
		{/if}
		{#if colour}
			<Row label={m.surface_colour()} tooltip={m.tooltip_surface_colour()}>
				<span class="inline-flex items-center gap-1.5">
					{#if colourMethod}<span class="text-muted-foreground">{colourMethod}</span>{/if}
					<span
						class="size-3.5 rounded-full border border-border"
						style="background-color: {colour}"
					></span>
				</span>
			</Row>
		{/if}
		{#snippet footer()}
			{#if outsideTemperatures}
				<TemperatureScale temperatures={outsideTemperatures} />
			{/if}
		{/snippet}
	</Section>
{/if}
