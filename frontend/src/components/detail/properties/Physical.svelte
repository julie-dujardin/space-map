<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import { NO_SURFACE_BODY_IDS } from '$lib/constants';
	import { isNaturalBodyType } from '$lib/types/objects';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatNumber, formatUnit, formatQuantity } from '$lib/format/quantities';
	import { formatTemperature } from '$lib/format/temperature';
	import { formatDuration } from '$lib/format/duration';
	import Section from './Section.svelte';
	import Row from './Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let wd = $derived(global?.wikidata);
	let sbdb = $derived(global?.sbdb);
	let orientation = $derived(global?.orientation);
	let radii = $derived(global?.radii);

	let sats = $derived(sbdb?.sats);

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
			wd?.temperature ||
			wd?.min_temperature ||
			wd?.max_temperature ||
			wd?.population ||
			wd?.absolute_magnitude != null ||
			sbdb?.H != null ||
			wd?.apparent_magnitude != null ||
			sbdb?.spec_B ||
			sbdb?.spec_T ||
			(sats != null && sats > 0)
	);
</script>

{#if hasContent}
	<Section title={m.physical_properties()}>
		{#if wd?.mass}
			<Row label={m.property_name_mass()} value={formatQuantity(wd.mass)} />
		{:else if sbdb?.mass}
			<Row label={m.property_name_mass()} value={formatQuantity(sbdb.mass)} />
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
		{#if surfaceAreaKm2 != null}
			<Row
				label={m.surface_area()}
				value={formatQuantity({ value: surfaceAreaKm2, unit: 'square_kilometre' }, true)}
			/>
		{/if}
		{#if wd?.density}
			<Row label={m.property_name_density()} value={formatQuantity(wd.density)} />
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
		{#if wd?.temperature}
			<Row label={m.property_name_temperature()} value={formatTemperature(wd.temperature)} />
		{/if}
		{#if wd?.min_temperature}
			<Row label={m.min_temperature()} value={formatTemperature(wd.min_temperature)} />
		{/if}
		{#if wd?.max_temperature}
			<Row label={m.max_temperature()} value={formatTemperature(wd.max_temperature)} />
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
		{#if sats != null && sats > 0}
			<Row
				label={m.known_satellites()}
				tooltip={m.tooltip_known_satellites()}
				value={String(sats)}
			/>
		{/if}
	</Section>
{/if}
