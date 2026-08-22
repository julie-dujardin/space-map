<script lang="ts">
	/**
	 * Whole-body facts, not point measurements — mass and size.
	 *
	 * Density lives here rather than under Interior: for many bodies it's the
	 * model's *input* (see `from_bulk_density`), not a conclusion, so placing
	 * it beside composition would state the premise as a result.
	 */
	import * as m from '$lib/paraglide/messages.js';
	import { NO_SURFACE_BODY_IDS } from '$lib/constants';
	import { isNaturalBodyType } from '$lib/types/objects';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import {
		formatDensity,
		formatNumber,
		formatQuantity,
		formatUnit,
		joinParts
	} from '$lib/format/quantities';
	import { ltrIsolate } from '$lib/format/bidi';
	import { diameterKmFromH, BRIGHT_ALBEDO, DARK_ALBEDO } from '$lib/math/h-magnitude';
	import { formatDuration } from '$lib/format/duration';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';

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
		const km = (value: string) => joinParts({ value, unit });
		if (a === b && b === c) {
			return [{ label: m.property_name_radius(), value: km(formatNumber(a)) }];
		}
		const equatorial = km(a === b ? formatNumber(a) : `${formatNumber(a)} × ${formatNumber(b)}`);
		return [
			{ label: m.equatorial_radius(), value: equatorial },
			{ label: m.polar_radius(), value: km(formatNumber(c)) }
		];
	});

	// Derived from whichever size source feeds the radius row; triaxial bodies
	// use Knud Thomsen's approximation (p=1.6075, ~1% error). Hidden for
	// non-natural bodies (radius bounds a model, not a sphere) and for the Sun
	// and gas/ice giants (radius bounds a gas envelope, not a surface).
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

	let hasContent = $derived(
		wd?.mass ||
			sbdb?.mass ||
			radii ||
			wd?.radius ||
			sbdb?.diameter ||
			sbdb?.extent ||
			wd?.length ||
			wd?.width ||
			estimatedDiameterKm ||
			surfaceAreaKm2 != null ||
			wd?.density ||
			wd?.surface_gravity ||
			rotationPeriodDays != null ||
			wd?.population ||
			(sats != null && sats > 0)
	);
</script>

{#if hasContent}
	<Section title={m.bulk_properties()}>
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
		{#if wd?.density}
			<Row label={m.property_name_density()} value={formatDensity(wd.density)} />
		{/if}
		{#if wd?.surface_gravity}
			<Row label={m.property_name_surface_gravity()} value={formatQuantity(wd.surface_gravity)} />
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
		{#if sats != null && sats > 0}
			<Row
				label={m.known_satellites()}
				tooltip={m.tooltip_known_satellites()}
				value={String(sats)}
			/>
		{/if}
	</Section>
{/if}
