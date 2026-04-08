<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import { Badge } from '$lib/components/ui/badge/index.js';
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
	}

	let physicalProps = $derived.by(() => {
		const props: Property[] = [];
		const wd = global?.wikidata;
		const sbdb = global?.sbdb;

		if (wd?.mass) props.push({ label: m.property_name_mass(), value: formatQuantity(wd.mass) });
		else if (sbdb?.mass)
			props.push({ label: m.property_name_mass(), value: formatQuantity(sbdb.mass) });

		if (wd?.radius)
			props.push({ label: m.property_name_radius(), value: formatQuantity(wd.radius) });
		else if (sbdb?.diameter)
			props.push({ label: m.diameter(), value: `${sbdb.diameter} ${formatUnit('kilometre')}` });

		if (sbdb?.extent) props.push({ label: m.extent(), value: sbdb.extent });
		if (wd?.density)
			props.push({ label: m.property_name_density(), value: formatQuantity(wd.density) });
		if (wd?.surface_gravity)
			props.push({
				label: m.property_name_surface_gravity(),
				value: formatQuantity(wd.surface_gravity)
			});
		if (sbdb?.albedo) props.push({ label: m.albedo(), value: formatNumber(sbdb.albedo) });
		if (sbdb?.rot_per)
			props.push({ label: m.rotation_period(), value: `${sbdb.rot_per} ${formatUnit('hour')}` });

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
				value: formatNumber(wd.absolute_magnitude)
			});
		else if (sbdb?.H != null)
			props.push({ label: m.absolute_magnitude_h(), value: formatNumber(sbdb.H) });

		if (wd?.apparent_magnitude != null)
			props.push({
				label: m.property_name_apparent_magnitude(),
				value: formatNumber(wd.apparent_magnitude)
			});

		if (sbdb?.spec_B) props.push({ label: m.spectral_type_smassii(), value: sbdb.spec_B });
		if (sbdb?.spec_T) props.push({ label: m.spectral_type_tholen(), value: sbdb.spec_T });

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
				value: `${formatNumber(sbdb.per_y)} ${formatUnit('year')}`
			});
		if (orbit?.a)
			props.push({
				label: m.semi_major_axis(),
				value: `${formatNumber(orbit.a)} ${formatUnit('astronomical_unit')}`
			});
		if (orbit?.e != null) props.push({ label: m.eccentricity(), value: formatNumber(orbit.e) });
		if (orbit?.i != null)
			props.push({ label: m.inclination(), value: `${formatNumber(orbit.i)}°` });
		if (orbit?.q)
			props.push({
				label: m.perihelion(),
				value: `${formatNumber(orbit.q)} ${formatUnit('astronomical_unit')}`
			});
		// Time of perihelion passage (parabolic orbits)
		const tp = orbit?.tp;
		if (tp != null)
			props.push({
				label: m.perihelion_time(),
				value: formatJulianDate(tp)
			});
		if (sbdb?.ad)
			props.push({
				label: m.aphelion(),
				value: `${formatNumber(sbdb.ad)} ${formatUnit('astronomical_unit')}`
			});
		if (sbdb?.moid)
			props.push({
				label: m.earth_moid(),
				value: `${formatNumber(sbdb.moid)} ${formatUnit('astronomical_unit')}`
			});
		if (sbdb?.t_jup) props.push({ label: m.tisserand_jupiter(), value: formatNumber(sbdb.t_jup) });
		if (sbdb?.condition_code != null)
			props.push({ label: m.condition_code(), value: formatNumber(sbdb.condition_code) });
		if (sbdb?.data_arc != null) {
			const years = sbdb.data_arc / 365.25;
			const value =
				years >= 1
					? `${formatNumber(years)} ${formatUnit('year')}`
					: `${formatNumber(sbdb.data_arc)} ${formatUnit('day')}`;
			props.push({ label: m.observation_arc(), value });
		}
		if (sbdb?.n_obs_used != null)
			props.push({ label: m.observations_used(), value: formatNumber(sbdb.n_obs_used) });
		if (sbdb?.last_obs) props.push({ label: m.last_observed(), value: sbdb.last_obs });

		return props;
	});
</script>

{#if physicalProps.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.physical_properties()}</h3>
		<Separator />
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#each physicalProps as prop (prop.label)}
				<dt class="text-muted-foreground">{ucfirst(prop.label)}</dt>
				<dd class="text-right">{prop.value}</dd>
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
				{#if isNeo}<Badge variant="outline">{m.neo()}</Badge>{/if}
				{#if isPha}<Badge variant="destructive">{m.pha()}</Badge>{/if}
			</div>
		{/if}
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#each orbitalProps as prop (prop.label)}
				<dt class="text-muted-foreground">{ucfirst(prop.label)}</dt>
				<dd class="text-right">{prop.value}</dd>
			{/each}
		</dl>
	</div>
{/if}
