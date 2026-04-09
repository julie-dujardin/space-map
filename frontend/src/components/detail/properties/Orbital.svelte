<script lang="ts">
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import type { OrbitalElements } from '$lib/types/objects';
	import { formatNumber, formatUnit } from '$lib/format/quantities';
	import { formatJulianDate } from '$lib/format/date';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		orbitElements?: OrbitalElements;
	}

	let { global, localized, orbitElements }: Props = $props();

	let orbit = $derived(orbitElements ?? global?.orbit);
	let sbdb = $derived(global?.sbdb);
	let orbitClass = $derived(sbdb?.class);
	let cometPrefix = $derived(sbdb?.prefix);
	let minorPlanetGroup = $derived(localized?.minor_planet_group);
	let isNeo = $derived(sbdb?.neo);
	let isPha = $derived(sbdb?.pha);

	let dataArcValue = $derived.by(() => {
		if (sbdb?.data_arc == null) return null;
		const years = sbdb.data_arc / 365.25;
		return years >= 1
			? `${formatNumber(years)} ${formatUnit('year')}`
			: `${formatNumber(sbdb.data_arc)} ${formatUnit('day')}`;
	});

	let hasContent = $derived(
		sbdb?.per_y ||
			orbit?.a ||
			orbit?.e != null ||
			orbit?.i != null ||
			orbit?.q ||
			orbit?.tp != null ||
			sbdb?.ad ||
			sbdb?.moid ||
			sbdb?.condition_code != null ||
			sbdb?.data_arc != null ||
			sbdb?.n_obs_used != null ||
			sbdb?.last_obs ||
			orbitClass ||
			cometPrefix ||
			minorPlanetGroup ||
			isNeo ||
			isPha
	);
</script>

{#if hasContent}
	<Section title={m.orbital_elements()}>
		{#snippet header()}
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
		{/snippet}
		{#if orbitClass}
			<Row label={m.orbit_class()} tooltip={m.tooltip_orbit_class()} value={orbitClass} />
		{/if}
		{#if cometPrefix}
			<Row label={m.comet_type()} value={cometPrefix} />
		{/if}
		{#if minorPlanetGroup && minorPlanetGroup.length > 0 && !orbitClass}
			<Row label={m.property_name_minor_planet_group()}>
				<EntityLinks entities={minorPlanetGroup} />
			</Row>
		{/if}
		{#if sbdb?.per_y}
			<Row
				label={m.orbital_period()}
				value={`${formatNumber(sbdb.per_y)} ${formatUnit('year')}`}
				tooltip={m.tooltip_orbital_period()}
			/>
		{/if}
		{#if orbit?.a}
			<Row
				label={m.semi_major_axis()}
				value={`${formatNumber(orbit.a)} ${formatUnit('astronomical_unit')}`}
				tooltip={m.tooltip_semi_major_axis()}
			/>
		{/if}
		{#if orbit?.q}
			<Row
				label={m.perihelion()}
				value={`${formatNumber(orbit.q)} ${formatUnit('astronomical_unit')}`}
				tooltip={m.tooltip_perihelion()}
			/>
		{/if}
		{#if orbit?.tp != null}
			<Row
				label={m.perihelion_time()}
				value={formatJulianDate(orbit.tp)}
				tooltip={m.tooltip_perihelion_time()}
			/>
		{/if}
		{#if sbdb?.ad}
			<Row
				label={m.aphelion()}
				value={`${formatNumber(sbdb.ad)} ${formatUnit('astronomical_unit')}`}
				tooltip={m.tooltip_aphelion()}
			/>
		{/if}
		{#if orbit?.e != null}
			<Row
				label={m.eccentricity()}
				value={formatNumber(orbit.e)}
				tooltip={m.tooltip_eccentricity()}
			/>
		{/if}
		{#if orbit?.i != null}
			<Row
				label={m.inclination()}
				value={`${formatNumber(orbit.i)}°`}
				tooltip={m.tooltip_inclination()}
			/>
		{/if}
		{#if sbdb?.moid}
			<Row
				label={m.earth_moid()}
				value={`${formatNumber(sbdb.moid)} ${formatUnit('astronomical_unit')}`}
				tooltip={m.tooltip_earth_moid()}
			/>
		{/if}
		{#if sbdb?.condition_code != null}
			<Row
				label={m.condition_code()}
				value={formatNumber(sbdb.condition_code)}
				tooltip={m.tooltip_condition_code()}
			/>
		{/if}
		{#if dataArcValue}
			<Row label={m.observation_arc()} value={dataArcValue} tooltip={m.tooltip_observation_arc()} />
		{/if}
		{#if sbdb?.n_obs_used != null}
			<Row
				label={m.observations_used()}
				value={formatNumber(sbdb.n_obs_used)}
				tooltip={m.tooltip_observations_used()}
			/>
		{/if}
		{#if sbdb?.last_obs}
			<Row label={m.last_observed()} value={sbdb.last_obs} />
		{/if}
	</Section>
{/if}
