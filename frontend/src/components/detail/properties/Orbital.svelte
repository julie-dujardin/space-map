<script lang="ts">
	import { getContext } from 'svelte';
	import { Badge } from '$lib/components/ui/badge/index.js';
	import * as Tooltip from '$lib/components/ui/tooltip/index.js';
	import * as m from '$lib/paraglide/messages.js';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { ObjectType, type OrbitalElements, type PositionedBody } from '$lib/types/objects';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import type { ContextManager } from '$lib/scene/context-manager.svelte';
	import { formatNumber, formatQuantityParts } from '$lib/format/quantities';
	import { formatDistance } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatJulianDate, formatJulianDateRelative } from '$lib/format/date';
	import { currentStateFromElements } from '$lib/math/orbit/state';
	import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
	import { sgp4PositionScene, sgp4State } from '$lib/math/orbit/sgp4';
	import { bodyQuaternion } from '$lib/math/orientation';
	import { cartesianToSpherical } from '$lib/math/spherical';
	import { AU_KM } from '$lib/math/units';
	import Section from './Section.svelte';
	import Row from './Row.svelte';
	import EntityLinks from './EntityLinks.svelte';

	const ctx = getContext<ContextManager>('ctx');

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

	// Localized provider names for OrbitalSource. SPICE reuses the ephemeris-kernel
	// label (vs the PCK-orientation one) since this row describes orbits. UNKNOWN
	// is omitted on purpose — handled by warning + null in `dataSourceLabel`.
	const ORBIT_SOURCE_LABEL: Partial<Record<OrbitalSource, () => string>> = {
		[OrbitalSource.HORIZONS]: m.source_horizons_name,
		[OrbitalSource.SBDB]: m.source_sbdb_name,
		[OrbitalSource.CELESTRAK]: m.source_celestrak_name,
		[OrbitalSource.SPICE]: m.source_spice_ephemeris_name
	};

	interface Props {
		global: GlobalObjectData | null;
		localized: LocalizedObjectData | null;
		body?: PositionedBody;
		orbitElements?: OrbitalElements;
		parentBody?: PositionedBody;
		jd: number;
	}

	let { global, localized, body, orbitElements, parentBody, jd }: Props = $props();

	let orbit = $derived(orbitElements ?? global?.orbit);
	// SGP4 when a satrec is available — Kepler from TLE elements drifts visibly
	// in r and v over hours due to J2/drag, even though the angular drift in
	// lat/lon is the more obvious symptom. Falls back to Kepler for everything
	// else (planets, moons, sun-orbiting bodies) where there's no satrec.
	let currentState = $derived.by(() => {
		if (!orbitElements) return null;
		if (body?.data.satrec) return sgp4State(body.data.satrec, jd);
		return currentStateFromElements(orbitElements, jd);
	});
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
	// Sub-point: lat/lon on the parent body directly below the orbiter. Uses
	// SGP4 when the body has a satrec (Earth sats) so J2 nodal regression and
	// drag are accounted for — pure-Kepler propagation from a TLE drifts in
	// phase by several degrees per day, which is highly visible in lat/lon
	// even though it barely shifts the radial altitude. Falls back to Kepler
	// for everything else, and rotates into the parent's body-fixed frame via
	// its IAU pole+spin. Hidden when the parent has no orientation metadata
	// loaded yet.
	let orbiterRelPos = $derived.by(() => {
		if (!showAltitude || !orbitElements) return null;
		if (body?.data.satrec) return sgp4PositionScene(body.data.satrec, jd);
		return orbitalElementsToPositionJD(orbitElements, jd);
	});
	let parentQuat = $derived(
		showAltitude && parentBody?.orientation
			? bodyQuaternion(parentBody.orientation, jd, parentBody.nutPrec)
			: null
	);
	let subPoint = $derived(
		orbiterRelPos && parentQuat
			? cartesianToSpherical(
					orbiterRelPos,
					[0, 0, 0],
					[parentQuat.x, parentQuat.y, parentQuat.z, parentQuat.w]
				)
			: null
	);
	let sbdb = $derived(global?.sbdb);
	let celestrak = $derived(global?.celestrak);
	let satPeriodDays = $derived(celestrak?.period != null ? celestrak.period / 1440 : null);
	// Fallback for bodies without SBDB/CelesTrak (planets, moons, Horizons-only):
	// derive period from mean motion. Only valid for elliptical orbits — n ≤ 0
	// flags parabolic, e ≥ 1 is hyperbolic (no period).
	let elementsPeriodDays = $derived(
		orbit?.n != null && orbit.n > 0 && orbit.e != null && orbit.e < 1 ? 360 / orbit.n : null
	);
	let orbitClass = $derived(sbdb?.class ? orbitClassLabel(sbdb.class) : null);
	let cometPrefix = $derived(sbdb?.prefix);
	let minorPlanetGroup = $derived(localized?.minor_planet_group);
	let isNeo = $derived(sbdb?.neo);
	let isPha = $derived(sbdb?.pha);

	let dataArc = $derived(sbdb?.data_arc != null ? formatDuration(sbdb.data_arc) : null);
	// Chebyshev-tracked bodies get osculating Kepler elements computed at an
	// arbitrary reference epoch just to drive the trail/sub-point math — that
	// epoch isn't a real observational epoch, so showing it is misleading.
	let isChebyshev = $derived(body != null && ctx?.chebStore?.has(body.data.id) === true);
	let epochJd = $derived(
		isChebyshev ? null : (orbitElements?.epoch ?? global?.orbit?.epoch_jd ?? null)
	);
	let epochValue = $derived(
		epochJd != null
			? `${formatJulianDate(epochJd)} (${formatJulianDateRelative(epochJd, jd)})`
			: null
	);

	let dataSourceLabel = $derived.by(() => {
		const src = body?.data.orbitalSource;
		if (src == null) return null;
		const label = ORBIT_SOURCE_LABEL[src];
		if (!label) {
			console.warn(`[Orbital] body ${body?.data.id} has UNKNOWN orbital source`);
			return null;
		}
		return label();
	});

	// Mirrors the renderer's dispatch order at renderer.ts:computePosition —
	// Chebyshev wins over SGP4 wins over Kepler. The detail panel's altitude /
	// orbital speed / sub-point are still derived from osculating elements (Kepler)
	// for Chebyshev-tracked bodies, so this label can disagree with the values
	// shown above. TODO: wire chebStore into currentState/orbiterRelPos to make
	// the panel consistent with the scene.
	let propagationMethodLabel = $derived.by(() => {
		if (!orbit) return null;
		if (body && ctx?.chebStore?.has(body.data.id)) return m.method_chebyshev();
		if (body?.data.satrec) return m.method_sgp4();
		if ((orbitElements?.omDot ?? 0) !== 0 || (orbitElements?.wDot ?? 0) !== 0)
			return m.method_kepler_j2();
		return m.method_kepler();
	});

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
			elementsPeriodDays != null ||
			epochJd != null ||
			(showApogeePerigee && (celestrak?.apogee != null || celestrak?.perigee != null)) ||
			dataSourceLabel != null ||
			propagationMethodLabel != null
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
				{...formatDuration(sbdb.per_y * 365.25)}
				tooltip={m.tooltip_orbital_period()}
			/>
		{:else if satPeriodDays != null}
			<Row
				label={m.orbital_period()}
				{...formatDuration(satPeriodDays)}
				tooltip={m.tooltip_orbital_period()}
			/>
		{:else if elementsPeriodDays != null}
			<Row
				label={m.orbital_period()}
				{...formatDuration(elementsPeriodDays)}
				tooltip={m.tooltip_orbital_period()}
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
				value={formatNumber(orbit.i)}
				unit="degree"
				tooltip={m.tooltip_inclination()}
			/>
		{/if}
		{#if orbit?.a}
			<Row
				label={m.semi_major_axis()}
				{...formatDistance(orbit.a)}
				tooltip={m.tooltip_semi_major_axis()}
			/>
		{/if}
		{#if orbit?.q}
			<Row label={m.perihelion()} {...formatDistance(orbit.q)} tooltip={m.tooltip_perihelion()} />
		{/if}
		{#if sbdb?.ad}
			<Row label={m.aphelion()} {...formatDistance(sbdb.ad)} tooltip={m.tooltip_aphelion()} />
		{/if}
		{#if showApogeePerigee && celestrak?.perigee != null}
			<Row
				label={m.perigee()}
				{...formatQuantityParts({ value: celestrak.perigee, unit: 'kilometre' })}
			/>
		{/if}
		{#if showApogeePerigee && celestrak?.apogee != null}
			<Row
				label={m.apogee()}
				{...formatQuantityParts({ value: celestrak.apogee, unit: 'kilometre' })}
			/>
		{/if}
		{#if orbit?.tp != null}
			<Row
				label={m.perihelion_time()}
				value={formatJulianDate(orbit.tp)}
				tooltip={m.tooltip_perihelion_time()}
			/>
		{/if}
		{#if altitudeKm != null && altitudeKm > 0}
			<Row
				label={m.altitude()}
				{...formatDistance(altitudeKm / AU_KM)}
				tooltip={m.tooltip_altitude()}
			/>
		{/if}
		{#if subPoint}
			<Row
				label={m.latitude()}
				value={formatNumber(subPoint.latitude)}
				unit="degree"
				tooltip={m.tooltip_latitude()}
			/>
			<Row
				label={m.longitude()}
				value={formatNumber(subPoint.longitude)}
				unit="degree"
				tooltip={m.tooltip_longitude()}
			/>
		{/if}
		{#if currentState}
			<Row
				label={m.orbital_speed()}
				{...formatQuantityParts({ value: currentState.vKms, unit: 'kilometre_per_second' })}
				tooltip={m.tooltip_orbital_speed()}
			/>
		{/if}
		{#if sbdb?.moid}
			<Row label={m.earth_moid()} {...formatDistance(sbdb.moid)} tooltip={m.tooltip_earth_moid()} />
		{/if}
		{#if sbdb?.condition_code != null}
			<Row
				label={m.condition_code()}
				value={formatNumber(sbdb.condition_code)}
				tooltip={m.tooltip_condition_code()}
			/>
		{/if}
		{#if dataArc}
			<Row label={m.observation_arc()} {...dataArc} tooltip={m.tooltip_observation_arc()} />
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
		{#if epochValue}
			<Row label={m.orbit_epoch()} value={epochValue} tooltip={m.tooltip_orbit_epoch()} />
		{/if}
		{#if dataSourceLabel}
			<Row
				label={m.orbit_data_source()}
				value={dataSourceLabel}
				tooltip={m.tooltip_orbit_data_source()}
			/>
		{/if}
		{#if propagationMethodLabel}
			<Row
				label={m.propagation_method()}
				value={propagationMethodLabel}
				tooltip={m.tooltip_propagation_method()}
			/>
		{/if}
	</Section>
{/if}
