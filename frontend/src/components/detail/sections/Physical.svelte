<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { NO_SURFACE_BODY_IDS } from '$lib/constants';
	import { isNaturalBodyType } from '$lib/types/objects';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatDensity, formatNumber, formatUnit, formatQuantity } from '$lib/format/quantities';
	import { ltrIsolate } from '$lib/format/bidi';
	import { diameterKmFromH, BRIGHT_ALBEDO, DARK_ALBEDO } from '$lib/math/h-magnitude';
	import { formatDuration } from '$lib/format/duration';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import TemperatureScale from './kit/TemperatureScale.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let wd = $derived(global?.wikidata);
	let sbdb = $derived(global?.sbdb);
	let orientation = $derived(global?.orientation);
	let radii = $derived(global?.radii);

	let sats = $derived(sbdb?.sats);

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

	let rotationPeriodDays = $derived(
		orientation?.w1 ? 360 / Math.abs(orientation.w1) : sbdb?.rot_per ? sbdb.rot_per / 24 : null
	);

	// {a, b} are the equatorial radii (X, Y); c is along the spin axis. Most
	// bodies have rotational symmetry (a==b) so the equatorial side collapses
	// to a single value; truly triaxial bodies (Pan, Phobos, ...) keep both.
	let radiiRows = $derived.by(() => {
		if (!radii) return null;
		const { a, b, c } = radii;
		const unit = formatUnit('kilometre');
		if (a === b && b === c) {
			return [{ label: m.property_name_radius(), value: `${formatNumber(a)} ${unit}` }];
		}
		const equatorial =
			a === b ? `${formatNumber(a)} ${unit}` : `${formatNumber(a)} × ${formatNumber(b)} ${unit}`;
		return [
			{ label: m.equatorial_radius(), value: equatorial },
			{ label: m.polar_radius(), value: `${formatNumber(c)} ${unit}` }
		];
	});

	// Surface area in km², derived from whichever size source the panel uses
	// for the radius row. Triaxial bodies use Knud Thomsen's approximation
	// (p=1.6075, ~1% error). Only natural bodies have a meaningful surface — a
	// spacecraft/debris radius bounds a model, not a sphere. Also hidden for the
	// Sun and gas/ice giants, whose radius bounds a gas envelope.
	let surfaceAreaKm2 = $derived.by(() => {
		if (!isNaturalBodyType(global?.type)) return null;
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

	let temperatures = $derived(wd?.temperatures ?? []);

	let hasContent = $derived(
		wd?.mass ||
			sbdb?.mass ||
			radii ||
			wd?.radius ||
			sbdb?.diameter ||
			sbdb?.extent ||
			wd?.length ||
			wd?.width ||
			wd?.density ||
			wd?.surface_gravity ||
			sbdb?.albedo ||
			rotationPeriodDays != null ||
			temperatures.length > 0 ||
			wd?.population ||
			wd?.absolute_magnitude != null ||
			sbdb?.H != null ||
			wd?.apparent_magnitude != null ||
			sbdb?.spec_B ||
			sbdb?.spec_T ||
			colour ||
			(sats != null && sats > 0)
	);
</script>

{#if hasContent}
	<Section title={m.physical_properties()}>
		{#if sbdb?.mass}
			<Row label={m.property_name_mass()} value={formatQuantity(sbdb.mass)} />
		{:else if wd?.mass}
			<Row label={m.property_name_mass()} value={formatQuantity(wd.mass)} />
		{/if}
		{#if radiiRows}
			{#each radiiRows as row (row.label)}
				<Row label={row.label} value={row.value} />
			{/each}
		{:else if wd?.radius}
			<Row label={m.property_name_radius()} value={formatQuantity(wd.radius)} />
		{:else if sbdb?.diameter}
			<Row label={m.diameter()} value={`${sbdb.diameter} ${formatUnit('kilometre')}`} />
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
				tooltip={m.tooltip_diameter_estimated()}
			/>
		{/if}
		{#if surfaceAreaKm2 != null}
			<Row
				label={m.surface_area()}
				value={formatQuantity({ value: surfaceAreaKm2, unit: 'square_kilometre' }, true)}
			/>
		{/if}
		{#if wd?.density}
			<Row label={m.property_name_density()} value={formatDensity(wd.density)} />
		{/if}
		{#if wd?.surface_gravity}
			<Row label={m.property_name_surface_gravity()} value={formatQuantity(wd.surface_gravity)} />
		{/if}
		{#if sbdb?.albedo}
			<Row label={m.albedo()} value={formatNumber(sbdb.albedo)} tooltip={m.tooltip_albedo()} />
		{/if}
		{#if rotationPeriodDays != null}
			<Row
				label={m.rotation_period()}
				value={formatDuration(rotationPeriodDays)}
				tooltip={m.tooltip_rotation_period()}
			/>
		{/if}
		{#if wd?.population}
			<Row label={m.property_name_population()} value={formatNumber(wd.population)} />
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
		{#if sats != null && sats > 0}
			<Row
				label={m.known_satellites()}
				tooltip={m.tooltip_known_satellites()}
				value={String(sats)}
			/>
		{/if}
		{#snippet footer()}
			{#if temperatures.length}
				<TemperatureScale entries={temperatures} />
			{/if}
		{/snippet}
	</Section>
{/if}
