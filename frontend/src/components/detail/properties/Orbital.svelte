<script lang="ts">
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { ObjectType, type OrbitalElements, type PositionedBody } from '$lib/types/objects';
	import { formatNumber, formatQuantity } from '$lib/format/quantities';
	import { formatDistance } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatJulianDate } from '$lib/format/date';
	import { currentStateFromElements } from '$lib/math/orbit/state';
	import { AU_KM } from '$lib/math/units';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	// Maps the OrbitClass enum name (`global.sbdb.class`, e.g. "MBA") to the
	// localized label. Mirrors the OrbitClass members in
	// data/src/space_map_data/models/object/sbdb.py — keep in sync when adding
	// classes there. Unknown ids fall through and render the raw id, so a new
	// class shows up as text rather than blanking the row.
	const ORBIT_CLASS_LABEL: Record<string, () => string> = {
		IEO: m.orbit_class_IEO,
		ATE: m.orbit_class_ATE,
		APO: m.orbit_class_APO,
		AMO: m.orbit_class_AMO,
		MCA: m.orbit_class_MCA,
		IMB: m.orbit_class_IMB,
		MBA: m.orbit_class_MBA,
		OMB: m.orbit_class_OMB,
		TJN: m.orbit_class_TJN,
		AST: m.orbit_class_AST,
		CEN: m.orbit_class_CEN,
		TNO: m.orbit_class_TNO,
		PAA: m.orbit_class_PAA,
		HYA: m.orbit_class_HYA,
		ETc: m.orbit_class_ETc,
		JFc: m.orbit_class_JFc,
		JFC: m.orbit_class_JFC,
		CTc: m.orbit_class_CTc,
		HTC: m.orbit_class_HTC,
		PAR: m.orbit_class_PAR,
		HYP: m.orbit_class_HYP,
		COM: m.orbit_class_COM
	};
	function orbitClassLabel(id: string): string {
		return ORBIT_CLASS_LABEL[id]?.() ?? id;
	}

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		orbitElements?: OrbitalElements;
		parentBody?: PositionedBody;
		jd: number;
	}

	let { global, localized, orbitElements, parentBody, jd }: Props = $props();

	let orbit = $derived(orbitElements ?? global?.orbit);
	let currentState = $derived(orbitElements ? currentStateFromElements(orbitElements, jd) : null);
	let showAltitude = $derived(
		currentState != null &&
			parentBody != null &&
			parentBody.data.radiusKm > 0 &&
			parentBody.data.objectType !== ObjectType.STAR &&
			parentBody.data.objectType !== ObjectType.BARYCENTER
	);
	let altitudeKm = $derived(
		showAltitude && currentState && parentBody ? currentState.rKm - parentBody.data.radiusKm : null
	);
	let sbdb = $derived(global?.sbdb);
	let celestrak = $derived(global?.celestrak);
	let satPeriodDays = $derived(celestrak?.period != null ? celestrak.period / 1440 : null);
	let orbitClass = $derived(sbdb?.class ? orbitClassLabel(sbdb.class) : null);
	let cometPrefix = $derived(sbdb?.prefix);
	let minorPlanetGroup = $derived(localized?.minor_planet_group);
	let isNeo = $derived(sbdb?.neo);
	let isPha = $derived(sbdb?.pha);

	let dataArcValue = $derived(sbdb?.data_arc != null ? formatDuration(sbdb.data_arc) : null);

	// Hide apogee/perigee for near-circular satellite orbits — they collapse to the altitude/semi-major axis.
	let showApogeePerigee = $derived(orbit?.e == null || orbit.e >= 0.01);

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
			isPha ||
			satPeriodDays != null ||
			(showApogeePerigee && (celestrak?.apogee != null || celestrak?.perigee != null))
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
				value={formatDuration(sbdb.per_y * 365.25)}
				tooltip={m.tooltip_orbital_period()}
			/>
		{:else if satPeriodDays != null}
			<Row
				label={m.orbital_period()}
				value={formatDuration(satPeriodDays)}
				tooltip={m.tooltip_orbital_period()}
			/>
		{/if}
		{#if orbit?.a}
			<Row
				label={m.semi_major_axis()}
				value={formatDistance(orbit.a)}
				tooltip={m.tooltip_semi_major_axis()}
			/>
		{/if}
		{#if currentState}
			<Row
				label={m.orbital_speed()}
				value={formatQuantity({ value: currentState.vKms, unit: 'kilometre_per_second' }, true)}
				tooltip={m.tooltip_orbital_speed()}
			/>
		{/if}
		{#if altitudeKm != null && altitudeKm > 0}
			<Row
				label={m.altitude()}
				value={formatDistance(altitudeKm / AU_KM)}
				tooltip={m.tooltip_altitude()}
			/>
		{/if}
		{#if orbit?.q}
			<Row
				label={m.perihelion()}
				value={formatDistance(orbit.q)}
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
			<Row label={m.aphelion()} value={formatDistance(sbdb.ad)} tooltip={m.tooltip_aphelion()} />
		{/if}
		{#if showApogeePerigee && celestrak?.apogee != null}
			<Row
				label={m.apogee()}
				value={formatQuantity({ value: celestrak.apogee, unit: 'kilometre' }, true)}
			/>
		{/if}
		{#if showApogeePerigee && celestrak?.perigee != null}
			<Row
				label={m.perigee()}
				value={formatQuantity({ value: celestrak.perigee, unit: 'kilometre' }, true)}
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
				value={formatDistance(sbdb.moid)}
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
