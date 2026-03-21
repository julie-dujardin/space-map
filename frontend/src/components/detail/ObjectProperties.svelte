<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import type { GlobalObjectData } from '$lib/object-data';

	interface Props {
		global: GlobalObjectData | null;
	}

	let { global }: Props = $props();

	interface Property {
		label: string;
		value: string;
	}

	function formatQuantity(q: { value: number; unit: string }): string {
		const unit = q.unit.replace(/_/g, ' ');
		return `${q.value.toLocaleString()} ${unit}`;
	}

	let physicalProps = $derived.by(() => {
		const props: Property[] = [];
		const wd = global?.wikidata;
		const sbdb = global?.sbdb;
		const phys = global?.physical;

		if (wd?.mass) props.push({ label: 'Mass', value: formatQuantity(wd.mass) });
		else if (phys?.mass_kg)
			props.push({ label: 'Mass', value: `${phys.mass_kg.toLocaleString()} kg` });

		if (wd?.radius) props.push({ label: 'Radius', value: formatQuantity(wd.radius) });
		else if (phys?.radius_km)
			props.push({ label: 'Radius', value: `${phys.radius_km.toLocaleString()} km` });
		else if (sbdb?.diameter) props.push({ label: 'Diameter', value: `${sbdb.diameter} km` });

		if (sbdb?.extent) props.push({ label: 'Extent', value: sbdb.extent });
		if (wd?.density) props.push({ label: 'Density', value: formatQuantity(wd.density) });
		if (wd?.surface_gravity)
			props.push({ label: 'Surface gravity', value: formatQuantity(wd.surface_gravity) });
		if (sbdb?.albedo) props.push({ label: 'Albedo', value: sbdb.albedo.toFixed(3) });
		if (sbdb?.rot_per) props.push({ label: 'Rotation period', value: `${sbdb.rot_per} h` });

		if (wd?.temperature)
			props.push({ label: 'Temperature', value: formatQuantity(wd.temperature) });
		if (wd?.min_temperature)
			props.push({ label: 'Min temperature', value: formatQuantity(wd.min_temperature) });
		if (wd?.max_temperature)
			props.push({ label: 'Max temperature', value: formatQuantity(wd.max_temperature) });

		const absMag = wd?.absolute_magnitude;
		if (typeof absMag === 'number')
			props.push({ label: 'Absolute magnitude', value: absMag.toString() });
		else if (absMag) props.push({ label: 'Absolute magnitude', value: formatQuantity(absMag) });
		else if (sbdb?.H != null)
			props.push({ label: 'Absolute magnitude (H)', value: sbdb.H.toString() });

		const appMag = wd?.apparent_magnitude;
		if (typeof appMag === 'number')
			props.push({ label: 'Apparent magnitude', value: appMag.toString() });
		else if (appMag) props.push({ label: 'Apparent magnitude', value: formatQuantity(appMag) });

		if (sbdb?.spec_B) props.push({ label: 'Spectral type (SMASSII)', value: sbdb.spec_B });
		if (sbdb?.spec_T) props.push({ label: 'Spectral type (Tholen)', value: sbdb.spec_T });

		return props;
	});

	let orbitalProps = $derived.by(() => {
		const props: Property[] = [];
		const orbit = global?.orbit;
		const sbdb = global?.sbdb;

		if (sbdb?.per_y)
			props.push({ label: 'Orbital period', value: `${sbdb.per_y.toFixed(2)} years` });
		if (orbit?.a) props.push({ label: 'Semi-major axis', value: `${orbit.a.toPrecision(6)} AU` });
		if (orbit?.e != null) props.push({ label: 'Eccentricity', value: orbit.e.toFixed(6) });
		if (orbit?.i != null) props.push({ label: 'Inclination', value: `${orbit.i.toFixed(4)}°` });
		if (sbdb?.q) props.push({ label: 'Perihelion', value: `${sbdb.q.toFixed(4)} AU` });
		if (sbdb?.ad) props.push({ label: 'Aphelion', value: `${sbdb.ad.toFixed(4)} AU` });
		if (sbdb?.moid) props.push({ label: 'Earth MOID', value: `${sbdb.moid.toFixed(6)} AU` });
		if (sbdb?.moid_jup)
			props.push({ label: 'Jupiter MOID', value: `${sbdb.moid_jup.toFixed(6)} AU` });
		if (sbdb?.t_jup) props.push({ label: 'Tisserand (Jupiter)', value: sbdb.t_jup.toFixed(3) });

		return props;
	});
</script>

{#if physicalProps.length > 0}
	<div class="flex flex-col gap-1">
		<h3 class="text-sm font-medium">Physical properties</h3>
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
		<h3 class="text-sm font-medium">Orbital elements</h3>
		<Separator />
		<dl class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
			{#each orbitalProps as prop (prop.label)}
				<dt class="text-muted-foreground">{prop.label}</dt>
				<dd class="text-right">{prop.value}</dd>
			{/each}
		</dl>
	</div>
{/if}
