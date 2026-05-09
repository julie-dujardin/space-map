<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatNumber, formatQuantityParts } from '$lib/format/quantities';
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
		if (a === b && b === c) {
			return [{ label: m.property_name_radius(), value: formatNumber(a), unit: 'kilometre' }];
		}
		const equatorial = a === b ? formatNumber(a) : `${formatNumber(a)} × ${formatNumber(b)}`;
		return [
			{ label: m.equatorial_radius(), value: equatorial, unit: 'kilometre' },
			{ label: m.polar_radius(), value: formatNumber(c), unit: 'kilometre' }
		];
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
			<Row label={m.property_name_mass()} {...formatQuantityParts(wd.mass)} />
		{:else if sbdb?.mass}
			<Row label={m.property_name_mass()} {...formatQuantityParts(sbdb.mass)} />
		{/if}
		{#if radiiRows}
			{#each radiiRows as row (row.label)}
				<Row label={row.label} value={row.value} unit={row.unit} />
			{/each}
		{:else if wd?.radius}
			<Row label={m.property_name_radius()} {...formatQuantityParts(wd.radius)} />
		{:else if sbdb?.diameter}
			<Row label={m.diameter()} value={String(sbdb.diameter)} unit="kilometre" />
		{/if}
		{#if wd?.length && !radii && !wd?.radius && !sbdb?.diameter}
			<Row label={m.property_name_length()} {...formatQuantityParts(wd.length)} />
		{/if}
		{#if wd?.width && !radii && !wd?.radius && !sbdb?.diameter}
			<Row label={m.property_name_width()} {...formatQuantityParts(wd.width)} />
		{/if}
		{#if sbdb?.extent && !radii && !wd?.radius && !sbdb?.diameter}
			<Row label={m.extent()} value={sbdb.extent} tooltip={m.tooltip_extent()} />
		{/if}
		{#if wd?.density}
			<Row label={m.property_name_density()} {...formatQuantityParts(wd.density)} />
		{/if}
		{#if wd?.surface_gravity}
			<Row label={m.property_name_surface_gravity()} {...formatQuantityParts(wd.surface_gravity)} />
		{/if}
		{#if sbdb?.albedo}
			<Row label={m.albedo()} value={formatNumber(sbdb.albedo)} tooltip={m.tooltip_albedo()} />
		{/if}
		{#if rotationPeriodDays != null}
			<Row
				label={m.rotation_period()}
				{...formatDuration(rotationPeriodDays)}
				tooltip={m.tooltip_rotation_period()}
			/>
		{/if}
		{#if wd?.temperature}
			<Row label={m.property_name_temperature()} {...formatTemperature(wd.temperature)} />
		{/if}
		{#if wd?.min_temperature}
			<Row label={m.property_name_min_temperature()} {...formatTemperature(wd.min_temperature)} />
		{/if}
		{#if wd?.max_temperature}
			<Row label={m.property_name_max_temperature()} {...formatTemperature(wd.max_temperature)} />
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
