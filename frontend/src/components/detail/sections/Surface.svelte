<script lang="ts">
	/**
	 * What it is like on the outside: how big it is, how it looks, how hot it
	 * is, what holds you down and how much radiation it delivers — everything
	 * measured at a surface, a cloud deck or a photosphere rather than deep
	 * inside.
	 *
	 * The temperature bar drops `core` readings: those are modelled central
	 * temperatures and belong to Interior, and a scale holding both would be
	 * useless anyway — the Sun's core runs 15.5 million K against a 5772 K
	 * photosphere.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import { NO_SURFACE_BODY_IDS } from '$lib/constants';
	import { isNaturalBodyType } from '$lib/types/objects';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatNumber, formatQuantity, formatUnit, joinParts } from '$lib/format/quantities';
	import { cancerRiskPerYear, formatDoseRate, timeToLethalDose } from '$lib/format/radiation';
	import { ltrIsolate } from '$lib/format/bidi';
	import { gravityLabel } from '$lib/format/gravity';
	import { diameterKmFromH, BRIGHT_ALBEDO, DARK_ALBEDO } from '$lib/math/h-magnitude';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import TemperatureScale from './kit/TemperatureScale.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let wd = $derived(global?.wikidata);
	let sbdb = $derived(global?.sbdb);
	let radii = $derived(global?.radii);
	// Size rows are for bodies only — a craft's dimensions belong to Mission.
	let natural = $derived(isNaturalBodyType(global?.type));

	// {a, b} are the equatorial radii (X, Y); c is along the spin axis, shown
	// doubled — the section quotes diameters everywhere, one convention. Most
	// bodies have rotational symmetry (a==b) so the equatorial side collapses
	// to a single value; truly triaxial bodies (Pan, Phobos, ...) keep both.
	let diameterRows = $derived.by(() => {
		if (!radii) return null;
		const { a, b, c } = radii;
		const unit = formatUnit('kilometre');
		const km = (value: string) => joinParts({ value, unit });
		if (a === b && b === c) {
			return [{ label: m.diameter(), value: km(formatNumber(2 * a)) }];
		}
		const equatorial = km(
			a === b ? formatNumber(2 * a) : `${formatNumber(2 * a)} × ${formatNumber(2 * b)}`
		);
		return [
			{ label: m.equatorial_diameter(), value: equatorial },
			{ label: m.polar_diameter(), value: km(formatNumber(2 * c)) }
		];
	});

	// Triaxial bodies use Knud Thomsen's approximation (p=1.6075, ~1% error).
	// Only spheroids get one — planets and dwarf planets — and the giants drop
	// out too (their radius bounds a gas envelope, not a surface).
	let surfaceAreaKm2 = $derived.by(() => {
		if (global?.type !== 'planet' && global?.type !== 'dwarf_planet') return null;
		if (global && NO_SURFACE_BODY_IDS.has(global.id)) return null;
		if (radii) {
			const { a, b, c } = radii;
			const p = 1.6075;
			const mean = (Math.pow(a * b, p) + Math.pow(a * c, p) + Math.pow(b * c, p)) / 3;
			return 4 * Math.PI * Math.pow(mean, 1 / p);
		}
		const radiusKm = wd?.radius
			? wd.radius.unit === 'kilometre'
				? wd.radius.value
				: wd.radius.unit === 'metre'
					? wd.radius.value / 1000
					: null
			: sbdb?.diameter
				? sbdb.diameter / 2
				: null;
		if (radiusKm == null) return null;
		return 4 * Math.PI * radiusKm * radiusKm;
	});

	// H-magnitude size estimate when no measured size exists (assumed albedo
	// matches the ingested DAMIT model scale); a measured albedo pins it.
	let estimatedDiameterKm = $derived.by(() => {
		if (!sbdb || sbdb.H == null) return null;
		if (radii || wd?.radius || sbdb.diameter || sbdb.extent || wd?.length || wd?.width) return null;
		if (sbdb.albedo) return { nominal: diameterKmFromH(sbdb.H, sbdb.albedo), range: null };
		return {
			nominal: diameterKmFromH(sbdb.H),
			range: [diameterKmFromH(sbdb.H, BRIGHT_ALBEDO), diameterKmFromH(sbdb.H, DARK_ALBEDO)]
		};
	});

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

	// Its own derived: Svelte's transform drops load-bearing parens around an
	// inline `natural && (a || b || …)` group.
	let hasSizeRows = $derived(
		!!(
			diameterRows ||
			wd?.radius ||
			sbdb?.diameter ||
			sbdb?.extent ||
			wd?.length ||
			wd?.width ||
			estimatedDiameterKm ||
			surfaceAreaKm2 != null ||
			wd?.surface_gravity ||
			wd?.population
		)
	);

	let hasContent = $derived(
		sbdb?.albedo ||
			outsideTemperatures != null ||
			wd?.absolute_magnitude != null ||
			sbdb?.H != null ||
			wd?.apparent_magnitude != null ||
			sbdb?.spec_B ||
			sbdb?.spec_T ||
			colour ||
			dose != null ||
			(natural && hasSizeRows)
	);
</script>

{#if hasContent}
	<Section title={m.surface()}>
		{#if natural}
			{#if diameterRows}
				{#each diameterRows as row (row.label)}
					<Row label={row.label} value={row.value} />
				{/each}
			{:else if wd?.radius}
				<Row
					label={m.diameter()}
					value={formatQuantity({ value: wd.radius.value * 2, unit: wd.radius.unit })}
				/>
			{:else if sbdb?.diameter}
				<Row
					label={m.diameter()}
					value={formatQuantity({ value: sbdb.diameter, unit: 'kilometre' })}
				/>
			{/if}
			{#if wd?.length && !radii && !wd?.radius && !sbdb?.diameter}
				<Row label={m.property_name_length()} value={formatQuantity(wd.length)} />
			{/if}
			{#if wd?.width && !radii && !wd?.radius && !sbdb?.diameter}
				<Row label={m.property_name_width()} value={formatQuantity(wd.width)} />
			{/if}
			{#if sbdb?.extent && !radii && !wd?.radius && !sbdb?.diameter}
				<Row label={m.extent()} value={sbdb.extent} tooltip={m.tooltip_extent()} />
			{/if}
			{#if estimatedDiameterKm}
				{@const km = formatUnit('kilometre', true)}
				<!-- LRI…PDI keeps the "(min – max km)" expression from bidi-reordering in RTL. -->
				<Row
					label={m.diameter()}
					value={estimatedDiameterKm.range
						? ltrIsolate(
								`${formatNumber(estimatedDiameterKm.nominal)} ${km} (${formatNumber(estimatedDiameterKm.range[0])} – ${formatNumber(estimatedDiameterKm.range[1])} ${km})`
							)
						: `${formatNumber(estimatedDiameterKm.nominal)} ${km}`}
					valueTooltip={m.tooltip_diameter_estimated()}
				/>
			{/if}
			{#if surfaceAreaKm2 != null}
				<Row
					label={m.surface_area()}
					value={formatQuantity({ value: surfaceAreaKm2, unit: 'square_kilometre' }, true)}
				/>
			{/if}
			{#if wd?.surface_gravity}
				<Row
					label={gravityLabel(global?.atmosphere?.pressure?.level)}
					value={formatQuantity(wd.surface_gravity)}
				/>
			{/if}
		{/if}
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
				label={m.property_name_absolute_magnitude()}
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
		{#if natural && wd?.population}
			<Row label={m.property_name_population()} value={formatNumber(wd.population)} />
		{/if}
		{#snippet footer()}
			{#if outsideTemperatures}
				<TemperatureScale temperatures={outsideTemperatures} />
			{/if}
		{/snippet}
	</Section>
{/if}
