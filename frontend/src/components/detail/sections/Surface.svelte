<script lang="ts">
	/**
	 * What it is like on the outside: how the body looks, how hot it is, and
	 * how much radiation it delivers — everything measured at a surface, a
	 * cloud deck or a photosphere rather than deep inside.
	 *
	 * The temperature bar drops `core` readings: those are modelled central
	 * temperatures and belong to Interior, and a scale holding both would be
	 * useless anyway — the Sun's core runs 15.5 million K against a 5772 K
	 * photosphere.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatNumber } from '$lib/format/quantities';
	import { cancerRiskPerYear, formatDoseRate, timeToLethalDose } from '$lib/format/radiation';
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

	let radiation = $derived(global?.radiation);

	// Published beats computed, and only one of the two is ever present.
	let dose = $derived(
		radiation?.surface_dose?.sv_per_day.value ?? radiation?.modelled_surface_dose?.sv_per_day
	);

	// A rate this large is an acute injury and a percentage of it is unreadable
	// — Europa's works out at two million percent of a lethal dose per day. The
	// environment's own `kind` decides which sentence applies, not the size of
	// the number, because the two are different quantities and not two ends of
	// one scale.
	let doseNote = $derived.by(() => {
		if (dose == null) return undefined;
		return radiation?.kind === 'trapped'
			? m.radiation_lethal_in({ duration: timeToLethalDose(dose) })
			: m.radiation_cancer_risk({ percent: cancerRiskPerYear(dose) });
	});

	// Where the figure came from, appended to the reading above: a measurement,
	// somebody's transport code, or ours.
	let doseProvenance = $derived.by(() => {
		if (radiation?.modelled_surface_dose) return m.radiation_from_model();
		if (radiation?.surface_dose?.sv_per_day.modelled) return m.radiation_modelled();
		return undefined;
	});

	let hasContent = $derived(
		sbdb?.albedo ||
			outsideTemperatures != null ||
			wd?.absolute_magnitude != null ||
			sbdb?.H != null ||
			wd?.apparent_magnitude != null ||
			sbdb?.spec_B ||
			sbdb?.spec_T ||
			colour ||
			dose != null
	);
</script>

{#if hasContent}
	<Section title={m.surface()}>
		{#if dose != null}
			<Row
				label={m.radiation()}
				tooltip={m.tooltip_radiation()}
				value={formatDoseRate(dose)}
				valueTooltip={[doseNote, doseProvenance].filter(Boolean).join(' ')}
			/>
		{/if}
		{#if radiation?.orbit_dose}
			<Row
				label={m.radiation_in_orbit()}
				tooltip={m.tooltip_radiation_in_orbit()}
				value={formatDoseRate(radiation.orbit_dose.sv_per_day.value)}
				valueTooltip={m.radiation_cancer_risk({
					percent: cancerRiskPerYear(radiation.orbit_dose.sv_per_day.value)
				})}
			/>
		{/if}
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
