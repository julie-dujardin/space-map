<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import type { GlobalObjectData } from '$lib/object-data';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	interface Property {
		label: string;
		value: string;
	}

	function formatUnit(unit: string): string {
		const symbolKey = `unit_${unit}`;
		const fn = (m as unknown as Record<string, (() => string) | undefined>)[symbolKey];
		return fn ? fn() : unit.replace(/_/g, ' ');
	}

	function formatNumber(n: number): string {
		return n.toLocaleString(getLocale());
	}

	function formatQuantity(q: { value: number; unit: string }): string {
		return `${formatNumber(q.value)} ${formatUnit(q.unit)}`;
	}

	let physicalProps = $derived.by(() => {
		const props: Property[] = [];
		const wd = global?.wikidata;
		const sbdb = global?.sbdb;
		const phys = global?.physical;

		if (wd?.mass) props.push({ label: m.mass(), value: formatQuantity(wd.mass) });
		else if (sbdb?.mass) props.push({ label: m.mass(), value: formatQuantity(sbdb.mass) });
		else if (phys?.mass_kg)
			props.push({
				label: m.mass(),
				value: `${formatNumber(phys.mass_kg)} ${formatUnit('kilogram')}`
			});

		if (wd?.radius) props.push({ label: m.radius(), value: formatQuantity(wd.radius) });
		else if (phys?.radius_km)
			props.push({
				label: m.radius(),
				value: `${formatNumber(phys.radius_km)} ${formatUnit('kilometre')}`
			});
		else if (sbdb?.diameter)
			props.push({ label: m.diameter(), value: `${sbdb.diameter} ${formatUnit('kilometre')}` });

		if (sbdb?.extent) props.push({ label: m.extent(), value: sbdb.extent });
		if (wd?.density) props.push({ label: m.density(), value: formatQuantity(wd.density) });
		if (wd?.surface_gravity)
			props.push({ label: m.surface_gravity(), value: formatQuantity(wd.surface_gravity) });
		if (sbdb?.albedo) props.push({ label: m.albedo(), value: sbdb.albedo.toFixed(3) });
		if (sbdb?.rot_per)
			props.push({ label: m.rotation_period(), value: `${sbdb.rot_per} ${formatUnit('hour')}` });

		if (wd?.temperature)
			props.push({ label: m.temperature(), value: formatQuantity(wd.temperature) });
		if (wd?.min_temperature)
			props.push({ label: m.min_temperature(), value: formatQuantity(wd.min_temperature) });
		if (wd?.max_temperature)
			props.push({ label: m.max_temperature(), value: formatQuantity(wd.max_temperature) });

		const absMag = wd?.absolute_magnitude;
		if (typeof absMag === 'number')
			props.push({ label: m.absolute_magnitude(), value: absMag.toString() });
		else if (absMag) props.push({ label: m.absolute_magnitude(), value: formatQuantity(absMag) });
		else if (sbdb?.H != null)
			props.push({ label: m.absolute_magnitude_h(), value: sbdb.H.toString() });

		const appMag = wd?.apparent_magnitude;
		if (typeof appMag === 'number')
			props.push({ label: m.apparent_magnitude(), value: appMag.toString() });
		else if (appMag) props.push({ label: m.apparent_magnitude(), value: formatQuantity(appMag) });

		if (sbdb?.spec_B) props.push({ label: m.spectral_type_smassii(), value: sbdb.spec_B });
		if (sbdb?.spec_T) props.push({ label: m.spectral_type_tholen(), value: sbdb.spec_T });

		return props;
	});

	let orbitalProps = $derived.by(() => {
		const props: Property[] = [];
		const orbit = global?.orbit;
		const sbdb = global?.sbdb;

		if (sbdb?.per_y)
			props.push({
				label: m.orbital_period(),
				value: `${sbdb.per_y.toFixed(2)} ${formatUnit('year')}`
			});
		if (orbit?.a)
			props.push({
				label: m.semi_major_axis(),
				value: `${orbit.a.toPrecision(6)} ${formatUnit('astronomical_unit')}`
			});
		if (orbit?.e != null) props.push({ label: m.eccentricity(), value: orbit.e.toFixed(6) });
		if (orbit?.i != null) props.push({ label: m.inclination(), value: `${orbit.i.toFixed(4)}°` });
		if (sbdb?.q)
			props.push({
				label: m.perihelion(),
				value: `${sbdb.q.toFixed(4)} ${formatUnit('astronomical_unit')}`
			});
		if (sbdb?.ad)
			props.push({
				label: m.aphelion(),
				value: `${sbdb.ad.toFixed(4)} ${formatUnit('astronomical_unit')}`
			});
		if (sbdb?.moid)
			props.push({
				label: m.earth_moid(),
				value: `${sbdb.moid.toFixed(6)} ${formatUnit('astronomical_unit')}`
			});
		if (sbdb?.moid_jup)
			props.push({
				label: m.jupiter_moid(),
				value: `${sbdb.moid_jup.toFixed(6)} ${formatUnit('astronomical_unit')}`
			});
		if (sbdb?.t_jup) props.push({ label: m.tisserand_jupiter(), value: sbdb.t_jup.toFixed(3) });

		return props;
	});
</script>

{#if physicalProps.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.physical_properties()}</h3>
		<Separator />
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#each physicalProps as prop (prop.label)}
				<dt class="text-muted-foreground">{prop.label}</dt>
				<dd class="text-right">{prop.value}</dd>
			{/each}
		</dl>
	</div>
{/if}

{#if orbitalProps.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">{m.orbital_elements()}</h3>
		<Separator />
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#each orbitalProps as prop (prop.label)}
				<dt class="text-muted-foreground">{prop.label}</dt>
				<dd class="text-right">{prop.value}</dd>
			{/each}
		</dl>
	</div>
{/if}
