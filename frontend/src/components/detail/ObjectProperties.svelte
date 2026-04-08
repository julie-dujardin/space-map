<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import type { OrbitalElements } from '$lib/types/objects';
	import { formatNumber, formatUnit, formatQuantity, ucfirst } from '$lib/format/quantities';
	import { formatTemperature } from '$lib/format/temperature';
	import { formatJulianDate } from '$lib/format/date';

	interface Props {
		global: GlobalObjectData | null;
		orbitElements?: OrbitalElements;
	}

	let { global, orbitElements }: Props = $props();

	interface Property {
		label: string;
		value: string;
		tooltip?: string;
	}

	let physicalProps = $derived.by(() => {
		const props: Property[] = [];
		const wd = global?.wikidata;
		const sbdb = global?.sbdb;

		if (wd?.mass)
			props.push({
				label: m.property_name_mass(),
				value: formatQuantity(wd.mass)
			});
		else if (sbdb?.mass)
			props.push({
				label: m.property_name_mass(),
				value: formatQuantity(sbdb.mass)
			});

		if (wd?.radius)
			props.push({
				label: m.property_name_radius(),
				value: formatQuantity(wd.radius)
			});
		else if (sbdb?.diameter)
			props.push({
				label: m.diameter(),
				value: `${sbdb.diameter} ${formatUnit('kilometre')}`
			});

		if (sbdb?.extent)
			props.push({ label: m.extent(), value: sbdb.extent, tooltip: m.tooltip_extent() });
		if (wd?.density)
			props.push({
				label: m.property_name_density(),
				value: formatQuantity(wd.density)
			});
		if (wd?.surface_gravity)
			props.push({
				label: m.property_name_surface_gravity(),
				value: formatQuantity(wd.surface_gravity)
			});
		if (sbdb?.albedo)
			props.push({
				label: m.albedo(),
				value: formatNumber(sbdb.albedo),
				tooltip: m.tooltip_albedo()
			});
		if (sbdb?.rot_per)
			props.push({
				label: m.rotation_period(),
				value: `${sbdb.rot_per} ${formatUnit('hour')}`,
				tooltip: m.tooltip_rotation_period()
			});

		if (wd?.temperature)
			props.push({
				label: m.property_name_temperature(),
				value: formatTemperature(wd.temperature)
			});
		if (wd?.min_temperature)
			props.push({
				label: m.property_name_min_temperature(),
				value: formatTemperature(wd.min_temperature)
			});
		if (wd?.max_temperature)
			props.push({
				label: m.property_name_max_temperature(),
				value: formatTemperature(wd.max_temperature)
			});

		if (wd?.population)
			props.push({
				label: m.property_name_population(),
				value: formatNumber(wd.population)
			});

		if (wd?.absolute_magnitude != null)
			props.push({
				label: m.property_name_absolute_magnitude(),
				value: formatNumber(wd.absolute_magnitude),
				tooltip: m.tooltip_absolute_magnitude()
			});
		else if (sbdb?.H != null)
			props.push({
				label: m.absolute_magnitude_h(),
				value: formatNumber(sbdb.H),
				tooltip: m.tooltip_absolute_magnitude_h()
			});

		if (wd?.apparent_magnitude != null)
			props.push({
				label: m.property_name_apparent_magnitude(),
				value: formatNumber(wd.apparent_magnitude),
				tooltip: m.tooltip_apparent_magnitude()
			});

		if (sbdb?.spec_B)
			props.push({
				label: m.spectral_type_smassii(),
				value: sbdb.spec_B,
				tooltip: m.tooltip_spectral_type_smassii()
			});
		if (sbdb?.spec_T)
			props.push({
				label: m.spectral_type_tholen(),
				value: sbdb.spec_T,
				tooltip: m.tooltip_spectral_type_tholen()
			});

		return props;
	});

	let isNeo = $derived(global?.sbdb?.neo);
	let isPha = $derived(global?.sbdb?.pha);

	let orbitalProps = $derived.by(() => {
		const props: Property[] = [];
		const orbit = orbitElements ?? global?.orbit;
		const sbdb = global?.sbdb;

		if (sbdb?.per_y)
			props.push({
				label: m.orbital_period(),
				value: `${formatNumber(sbdb.per_y)} ${formatUnit('year')}`,
				tooltip: m.tooltip_orbital_period()
			});
		if (orbit?.a)
			props.push({
				label: m.semi_major_axis(),
				value: `${formatNumber(orbit.a)} ${formatUnit('astronomical_unit')}`,
				tooltip: m.tooltip_semi_major_axis()
			});
		if (orbit?.e != null)
			props.push({
				label: m.eccentricity(),
				value: formatNumber(orbit.e),
				tooltip: m.tooltip_eccentricity()
			});
		if (orbit?.i != null)
			props.push({
				label: m.inclination(),
				value: `${formatNumber(orbit.i)}°`,
				tooltip: m.tooltip_inclination()
			});
		if (orbit?.q)
			props.push({
				label: m.perihelion(),
				value: `${formatNumber(orbit.q)} ${formatUnit('astronomical_unit')}`,
				tooltip: m.tooltip_perihelion()
			});
		const tp = orbit?.tp;
		if (tp != null)
			props.push({
				label: m.perihelion_time(),
				value: formatJulianDate(tp),
				tooltip: m.tooltip_perihelion_time()
			});
		if (sbdb?.ad)
			props.push({
				label: m.aphelion(),
				value: `${formatNumber(sbdb.ad)} ${formatUnit('astronomical_unit')}`,
				tooltip: m.tooltip_aphelion()
			});
		if (sbdb?.moid)
			props.push({
				label: m.earth_moid(),
				value: `${formatNumber(sbdb.moid)} ${formatUnit('astronomical_unit')}`,
				tooltip: m.tooltip_earth_moid()
			});
		if (sbdb?.condition_code != null)
			props.push({
				label: m.condition_code(),
				value: formatNumber(sbdb.condition_code),
				tooltip: m.tooltip_condition_code()
			});
		if (sbdb?.data_arc != null) {
			const years = sbdb.data_arc / 365.25;
			const value =
				years >= 1
					? `${formatNumber(years)} ${formatUnit('year')}`
					: `${formatNumber(sbdb.data_arc)} ${formatUnit('day')}`;
			props.push({ label: m.observation_arc(), value, tooltip: m.tooltip_observation_arc() });
		}
		if (sbdb?.n_obs_used != null)
			props.push({
				label: m.observations_used(),
				value: formatNumber(sbdb.n_obs_used),
				tooltip: m.tooltip_observations_used()
			});
		if (sbdb?.last_obs)
			props.push({
				label: m.last_observed(),
				value: sbdb.last_obs
			});

		return props;
	});
</script>

{#snippet propRow(prop: Property)}
	<dt class="text-muted-foreground">
		{#if prop.tooltip}
			<Tooltip.Root>
				<Tooltip.Trigger>
					{#snippet child({ props })}
						<span class="cursor-help decoration-dotted underline underline-offset-2" {...props}>
							{ucfirst(prop.label)}
						</span>
					{/snippet}
				</Tooltip.Trigger>
				<Tooltip.Content>{prop.tooltip}</Tooltip.Content>
			</Tooltip.Root>
		{:else}
			{ucfirst(prop.label)}
		{/if}
	</dt>
	<dd class="text-right">{prop.value}</dd>
{/snippet}

{#if physicalProps.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.physical_properties()}</h3>
		<Separator />
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#each physicalProps as prop (prop.label)}
				{@render propRow(prop)}
			{/each}
		</dl>
	</div>
{/if}

{#if orbitalProps.length > 0 || isNeo || isPha}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.orbital_elements()}</h3>
		<Separator />
		{#if isNeo || isPha}
			<div class="flex gap-1.5 mb-1">
				{#if isNeo}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<span {...props}><Badge variant="outline">{m.neo()}</Badge></span>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{m.tooltip_neo()}</Tooltip.Content>
					</Tooltip.Root>
				{/if}
				{#if isPha}
					<Tooltip.Root>
						<Tooltip.Trigger>
							{#snippet child({ props })}
								<span {...props}><Badge variant="destructive">{m.pha()}</Badge></span>
							{/snippet}
						</Tooltip.Trigger>
						<Tooltip.Content>{m.tooltip_pha()}</Tooltip.Content>
					</Tooltip.Root>
				{/if}
			</div>
		{/if}
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#each orbitalProps as prop (prop.label)}
				{@render propRow(prop)}
			{/each}
		</dl>
	</div>
{/if}
