<script lang="ts">
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import { formatNumber, formatUnit, formatQuantity } from '$lib/format/quantities';
	import { formatTemperature } from '$lib/format/temperature';
	import Section from './Section.svelte';
	import Row from './Row.svelte';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	let wd = $derived(global?.wikidata);
	let sbdb = $derived(global?.sbdb);

	let hasContent = $derived(
		wd?.mass ||
			sbdb?.mass ||
			wd?.radius ||
			sbdb?.diameter ||
			sbdb?.extent ||
			wd?.length ||
			wd?.width ||
			wd?.density ||
			wd?.surface_gravity ||
			sbdb?.albedo ||
			sbdb?.rot_per ||
			wd?.temperature ||
			wd?.min_temperature ||
			wd?.max_temperature ||
			wd?.population ||
			wd?.absolute_magnitude != null ||
			sbdb?.H != null ||
			wd?.apparent_magnitude != null ||
			sbdb?.spec_B ||
			sbdb?.spec_T
	);
</script>

{#if hasContent}
	<Section title={m.physical_properties()}>
		{#if wd?.mass}
			<Row label={m.property_name_mass()} value={formatQuantity(wd.mass)} />
		{:else if sbdb?.mass}
			<Row label={m.property_name_mass()} value={formatQuantity(sbdb.mass)} />
		{/if}
		{#if wd?.radius}
			<Row label={m.property_name_radius()} value={formatQuantity(wd.radius)} />
		{:else if sbdb?.diameter}
			<Row label={m.diameter()} value={`${sbdb.diameter} ${formatUnit('kilometre')}`} />
		{/if}
		{#if wd?.length}
			<Row label={m.property_name_length()} value={formatQuantity(wd.length)} />
		{/if}
		{#if wd?.width}
			<Row label={m.property_name_width()} value={formatQuantity(wd.width)} />
		{/if}
		{#if sbdb?.extent}
			<Row label={m.extent()} value={sbdb.extent} tooltip={m.tooltip_extent()} />
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
		{#if sbdb?.rot_per}
			<Row
				label={m.rotation_period()}
				value={`${sbdb.rot_per} ${formatUnit('hour')}`}
				tooltip={m.tooltip_rotation_period()}
			/>
		{/if}
		{#if wd?.temperature}
			<Row label={m.property_name_temperature()} value={formatTemperature(wd.temperature)} />
		{/if}
		{#if wd?.min_temperature}
			<Row
				label={m.property_name_min_temperature()}
				value={formatTemperature(wd.min_temperature)}
			/>
		{/if}
		{#if wd?.max_temperature}
			<Row
				label={m.property_name_max_temperature()}
				value={formatTemperature(wd.max_temperature)}
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
	</Section>
{/if}
