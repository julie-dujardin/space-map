<script lang="ts">
	import { Separator } from '$lib/components/ui/separator/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import type { OrbitalElements } from '$lib/types/objects';
	import { convertTemperature } from '$lib/math/units';

	interface Props {
		global: GlobalObjectData | null;
		orbitElements?: OrbitalElements;
	}

	let { global, orbitElements }: Props = $props();

	interface Property {
		label: string;
		value: string;
	}

	function formatUnit(unit: string, short?: boolean): string {
		const symbolKey = short ? `unit_symbol_${unit}` : `unit_name_${unit}`;
		const fn = (m as unknown as Record<string, (() => string) | undefined>)[symbolKey];
		return fn ? fn() : unit.replace(/_/g, ' ');
	}

	function formatNumber(n: number): string {
		if (!Number.isFinite(n)) return String(n);
		const intDigits = Math.floor(Math.abs(n)) === 0 ? 0 : Math.floor(Math.log10(Math.abs(n))) + 1;
		const fracDigits = Math.max(0, 3 - intDigits);
		const rounded = fracDigits === 0 ? Math.round(n) : parseFloat(n.toFixed(fracDigits));
		return rounded.toLocaleString(getLocale());
	}

	function ucfirst(s: string): string {
		return s.charAt(0).toUpperCase() + s.slice(1);
	}

	function formatQuantity(q: { value: number; unit: string }, short_unit?: boolean): string {
		return `${formatNumber(q.value)} ${formatUnit(q.unit, short_unit)}`;
	}

	function formatTemperature(q: { value: number; unit: string }): string {
		return formatQuantity(convertTemperature(q), true);
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
		if (sbdb?.albedo) props.push({ label: m.albedo(), value: sbdb.albedo.toFixed(3) });
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

		if (wd?.absolute_magnitude != null)
			props.push({
				label: m.property_name_absolute_magnitude(),
				value: wd.absolute_magnitude.toString()
			});
		else if (sbdb?.H != null)
			props.push({ label: m.absolute_magnitude_h(), value: sbdb.H.toString() });

		if (wd?.apparent_magnitude != null)
			props.push({
				label: m.property_name_apparent_magnitude(),
				value: wd.apparent_magnitude.toString()
			});

		if (sbdb?.spec_B) props.push({ label: m.spectral_type_smassii(), value: sbdb.spec_B });
		if (sbdb?.spec_T) props.push({ label: m.spectral_type_tholen(), value: sbdb.spec_T });

		return props;
	});

	let orbitalProps = $derived.by(() => {
		const props: Property[] = [];
		const orbit = orbitElements ?? global?.orbit;
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
				<dt class="text-muted-foreground">{ucfirst(prop.label)}</dt>
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
				<dt class="text-muted-foreground">{ucfirst(prop.label)}</dt>
				<dd class="text-right">{prop.value}</dd>
			{/each}
		</dl>
	</div>
{/if}
