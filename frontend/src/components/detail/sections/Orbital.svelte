<script lang="ts">
	import { getContext } from 'svelte';
	import Link from './kit/Link.svelte';
	import * as m from '$lib/paraglide/messages.js';
	import { archiveLabel, archiveUrl } from '$lib/credits/archive-labels';
	import type { GlobalObjectData, LocalizedObjectData } from '$lib/fetch/objects/object-data';
	import { ObjectType, type OrbitalElements, type PositionedBody } from '$lib/types/objects';
	import {
		OrbitalSource,
		PROBE_METHOD_CHEBYSHEV,
		PROBE_METHOD_KEPLER_DRIFT,
		PROBE_METHOD_KEPLER_PURE,
		PROBE_METHOD_UNCOVERABLE
	} from '$lib/fetch/position/format';
	import {
		findSubChunkIndex,
		isLandedAt,
		jdToEt,
		landedOpenEnded,
		landedPositionAt
	} from '$lib/fetch/position/probes/propagate';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { formatDegrees, formatNumber, formatQuantity } from '$lib/format/quantities';
	import { formatDistance } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatIsoDate, formatJulianDate, formatJulianDateRelative } from '$lib/format/date';
	import { currentStateFromElements } from '$lib/math/orbit/state';
	import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
	import { sgp4PositionScene, sgp4State } from '$lib/math/orbit/sgp4';
	import { bodyQuaternion } from '$lib/math/orientation';
	import { cartesianToSpherical } from '$lib/math/spherical';
	import { AU_KM } from '$lib/math/units';
	import { classifyEarthOrbit, orbitClassLabel } from '$lib/charts/orbit-zones';
	import type { EntityRef } from '$lib/fetch/objects/object-data';
	import Section from './kit/Section.svelte';
	import Row from './kit/Row.svelte';
	import EntityLinks from './kit/EntityLinks.svelte';

	const ctx = getContext<ContextManager>('ctx');

	// Fallback when the global JSON predates `ephemeris_source`.
	const ORBIT_SOURCE_LABEL: Partial<Record<OrbitalSource, () => string>> = {
		[OrbitalSource.HORIZONS]: m.source_horizons_name,
		[OrbitalSource.SBDB]: m.source_sbdb_name,
		[OrbitalSource.CELESTRAK]: m.source_celestrak_name,
		[OrbitalSource.SPICE]: m.source_spice_ephemeris_name,
		[OrbitalSource.SBDB_MOON]: m.source_sbdb_name,
		[OrbitalSource.SPICE_PROBE]: m.source_spice_ephemeris_name
	};

	// Archive ids feeding archiveUrl(); used when only the enum source is known.
	const ORBIT_SOURCE_ARCHIVE: Partial<Record<OrbitalSource, string>> = {
		[OrbitalSource.HORIZONS]: 'horizons',
		[OrbitalSource.SBDB]: 'sbdb',
		[OrbitalSource.CELESTRAK]: 'celestrak',
		[OrbitalSource.SPICE]: 'naif',
		[OrbitalSource.SBDB_MOON]: 'sbdb',
		[OrbitalSource.SPICE_PROBE]: 'naif'
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

	// Landed-probe detection: a SPICE_PROBE whose current chunk carries a
	// trailing METHOD_LANDED record covering `jd` is sitting on a body's
	// surface. The orbital-elements section makes no sense for these — show
	// a position section (lat/lng/altitude) instead.
	let landedProbe = $derived.by(() => {
		if (body?.data.orbitalSource !== OrbitalSource.SPICE_PROBE || !ctx?.probeStore) {
			return null;
		}
		const probe = ctx.probeStore.probe(body.data.id, jd);
		if (!probe || !probe.landed || !isLandedAt(probe, jd)) return null;
		return { landed: probe.landed, holdPastEnd: landedOpenEnded(probe) };
	});
	let landedSample = $derived.by(() => {
		if (!landedProbe) return null;
		return landedPositionAt(landedProbe.landed, jd, landedProbe.holdPastEnd);
	});
	let landedBody = $derived.by(() => {
		if (!landedProbe) return null;
		return ctx?.bodies.bodiesById.get(`naif-${landedProbe.landed.bodyNaifId}`) ?? null;
	});
	let landedBodyName = $derived(landedBody?.data.name ?? null);

	let orbit = $derived(orbitElements ?? global?.orbit);
	// SGP4 when a satrec is available, since Kepler from TLE elements drifts
	// visibly in r and v over hours due to J2/drag. Falls back to Kepler
	// everywhere else (planets, moons, sun-orbiting bodies).
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
	// Sub-point: lat/lon on the parent directly below the orbiter. SGP4 when a
	// satrec exists, since a TLE's pure-Kepler drift shows up strongly in
	// lat/lon even though it barely shifts altitude; Kepler otherwise, rotated
	// into the parent's body-fixed frame via its IAU pole+spin.
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
	// Earth sats and probes surface altitude/speed/period in the ObjectStats
	// cards instead, so those rows are suppressed here to avoid duplicating them.
	let isEarthSat = $derived(celestrak?.orbit_center === 'earth');
	let inObjectStats = $derived(
		isEarthSat || body?.data.orbitalSource === OrbitalSource.SPICE_PROBE
	);
	let satPeriodDays = $derived(celestrak?.period != null ? celestrak.period / 1440 : null);
	// Fallback for bodies without SBDB/CelesTrak (planets, moons, Horizons-only):
	// derive period from mean motion. Only valid for elliptical orbits — n ≤ 0
	// flags parabolic, e ≥ 1 is hyperbolic (no period).
	let elementsPeriodDays = $derived(
		orbit?.n != null && orbit.n > 0 && orbit.e != null && orbit.e < 1 ? 360 / orbit.n : null
	);
	let orbitClass = $derived(sbdb?.class ? orbitClassLabel(sbdb.class) : null);
	// Earth-sat orbit zones: derived from peri/apo/inc since membership lookup
	// from the static index would be 14× larger payload for one chip row.
	let satOrbitClasses = $derived(
		celestrak?.orbit_center === 'earth'
			? classifyEarthOrbit(celestrak.perigee, celestrak.apogee, orbit?.i)
			: []
	);
	let satOrbitClassRefs = $derived<EntityRef[]>(
		satOrbitClasses.map((c) => ({
			name: orbitClassLabel(c),
			primary_type: 'group',
			primary_id: `class-${c}`
		}))
	);
	let cometPrefix = $derived(sbdb?.prefix);
	let minorPlanetGroup = $derived(localized?.minor_planet_group);

	let dataArcValue = $derived(sbdb?.data_arc != null ? formatDuration(sbdb.data_arc) : null);
	// Chebyshev-tracked bodies get osculating Kepler elements computed regularly to
	// display trails — that epoch isn't a real observational one, so showing it is misleading.
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
		const archive = archiveLabel(global?.ephemeris_source);
		if (archive) return archive;
		const src = body?.data.orbitalSource;
		// UNKNOWN is the legit "no provenance shipped" sentinel (hand-authored
		// elements, or files pre-dating the source byte) — show nothing, no warn.
		if (src == null || src === OrbitalSource.UNKNOWN) return null;
		const label = ORBIT_SOURCE_LABEL[src];
		if (!label) {
			console.warn(`[Orbital] body ${body?.data.id} has UNKNOWN orbital source`);
			return null;
		}
		return label();
	});

	let dataSourceUrl = $derived.by(() => {
		const archive = global?.ephemeris_source;
		if (archive) return archiveUrl(archive);
		const src = body?.data.orbitalSource;
		return src != null ? archiveUrl(ORBIT_SOURCE_ARCHIVE[src]) : null;
	});

	// Mirrors the renderer's dispatch order (renderer.ts:computePosition):
	// Chebyshev > SGP4 > Kepler. Altitude/speed/sub-point above still derive
	// from osculating Kepler elements for Chebyshev-tracked bodies, so this
	// label can disagree with those values.
	// TODO: wire chebStore into currentState/orbiterRelPos for consistency.
	let propagationMethodLabel = $derived.by(() => {
		if (!orbit) return null;
		// Probes dispatch per sub-chunk in the binary; report whichever method
		// covers the current jd, not the osculating-Kepler fallback the renderer
		// hands us via body.orbitElements.
		if (body?.data.orbitalSource === OrbitalSource.SPICE_PROBE && ctx?.probeStore) {
			const probe = ctx.probeStore.probe(body.data.id, jd);
			if (probe) {
				const idx = findSubChunkIndex(probe, jdToEt(jd));
				if (idx >= 0) {
					const method = probe.subChunks[idx].method;
					if (method === PROBE_METHOD_CHEBYSHEV) return m.method_chebyshev();
					if (method === PROBE_METHOD_KEPLER_DRIFT) return m.method_kepler_drift();
					if (method === PROBE_METHOD_KEPLER_PURE) return m.method_kepler();
					if (method === PROBE_METHOD_UNCOVERABLE) return null;
				}
			}
		}
		if (body && ctx?.chebStore?.has(body.data.id)) return m.method_chebyshev();
		if (body?.data.satrec) return m.method_sgp4();
		if ((orbitElements?.omDot ?? 0) !== 0 || (orbitElements?.wDot ?? 0) !== 0)
			return m.method_kepler_j2();
		return m.method_kepler();
	});

	// Hide apogee/perigee for near-circular satellite orbits — they collapse to the altitude/semi-major axis.
	let showApogeePerigee = $derived(orbit?.e == null || orbit.e >= 0.01);

	// The Sun's orbit is its around the solar system barycenter.
	// Suppress until we get milky-way relative orbits.
	let isStar = $derived(body?.data.objectType === ObjectType.STAR);

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
			satPeriodDays != null ||
			elementsPeriodDays != null ||
			epochJd != null ||
			(showApogeePerigee && (celestrak?.apogee != null || celestrak?.perigee != null)) ||
			dataSourceLabel != null ||
			propagationMethodLabel != null
	);
</script>

{#if landedProbe && landedSample}
	<Section title={m.surface_position()}>
		<Row
			label={m.latitude()}
			value={formatDegrees(landedSample.latDeg)}
			tooltip={m.tooltip_latitude()}
		/>
		<Row
			label={m.longitude()}
			value={formatDegrees(landedSample.lngDeg)}
			tooltip={m.tooltip_longitude()}
		/>
		<Row
			label={m.altitude()}
			value={formatQuantity({ value: landedSample.altM, unit: 'metre' }, true)}
			tooltip={m.tooltip_altitude()}
		/>
		{#if landedBodyName}
			<Row label={m.landed_on()} value={landedBodyName} tooltip={m.tooltip_landed_on()} />
		{/if}
		<Row
			label={m.surface_state()}
			value={landedProbe.landed.isStatic ? m.surface_state_stationary() : m.surface_state_mobile()}
			tooltip={m.tooltip_surface_state()}
		/>
		{#if dataSourceLabel}
			<Row label={m.orbit_data_source()} tooltip={m.tooltip_orbit_data_source()}>
				{#if dataSourceUrl}
					<Link href={dataSourceUrl} external>{dataSourceLabel}</Link>
				{:else}
					{dataSourceLabel}
				{/if}
			</Row>
		{/if}
	</Section>
{:else if hasContent && !isStar}
	<Section title={m.orbital_elements()}>
		{#if satOrbitClassRefs.length > 0}
			<Row label={m.orbit_class()} tooltip={m.tooltip_orbit_class()}>
				<EntityLinks entities={satOrbitClassRefs} />
			</Row>
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
		{:else if satPeriodDays != null && !inObjectStats}
			<Row
				label={m.orbital_period()}
				value={formatDuration(satPeriodDays)}
				tooltip={m.tooltip_orbital_period()}
			/>
		{:else if elementsPeriodDays != null && !inObjectStats}
			<Row
				label={m.orbital_period()}
				value={formatDuration(elementsPeriodDays)}
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
				value={formatDegrees(orbit.i)}
				tooltip={m.tooltip_inclination()}
			/>
		{/if}
		{#if orbit?.a}
			<Row
				label={m.semi_major_axis()}
				value={formatDistance(orbit.a)}
				tooltip={m.tooltip_semi_major_axis()}
			/>
		{/if}
		{#if orbit?.q}
			<Row
				label={m.perihelion()}
				value={formatDistance(orbit.q)}
				tooltip={m.tooltip_perihelion()}
			/>
		{/if}
		{#if sbdb?.ad}
			<Row label={m.aphelion()} value={formatDistance(sbdb.ad)} tooltip={m.tooltip_aphelion()} />
		{/if}
		{#if showApogeePerigee && celestrak?.perigee != null}
			<Row
				label={m.perigee()}
				value={formatQuantity({ value: celestrak.perigee, unit: 'kilometre' }, true)}
			/>
		{/if}
		{#if showApogeePerigee && celestrak?.apogee != null}
			<Row
				label={m.apogee()}
				value={formatQuantity({ value: celestrak.apogee, unit: 'kilometre' }, true)}
			/>
		{/if}
		{#if orbit?.tp != null}
			<Row
				label={m.perihelion_time()}
				value={formatJulianDate(orbit.tp)}
				tooltip={m.tooltip_perihelion_time()}
			/>
		{/if}
		{#if altitudeKm != null && altitudeKm > 0 && !inObjectStats}
			<Row
				label={m.altitude()}
				value={formatDistance(altitudeKm / AU_KM)}
				tooltip={m.tooltip_altitude()}
			/>
		{/if}
		{#if subPoint}
			<Row
				label={m.latitude()}
				value={formatDegrees(subPoint.latitude)}
				tooltip={m.tooltip_latitude()}
			/>
			<Row
				label={m.longitude()}
				value={formatDegrees(subPoint.longitude)}
				tooltip={m.tooltip_longitude()}
			/>
		{/if}
		{#if currentState && !inObjectStats}
			<Row
				label={m.orbital_speed()}
				value={formatQuantity({ value: currentState.vKms, unit: 'kilometre_per_second' }, true)}
				tooltip={m.tooltip_orbital_speed()}
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
			<Row label={m.last_observed()} value={formatIsoDate(sbdb.last_obs)} />
		{/if}
		{#if epochValue}
			<Row label={m.orbit_epoch()} value={epochValue} tooltip={m.tooltip_orbit_epoch()} />
		{/if}
		{#if dataSourceLabel}
			<Row label={m.orbit_data_source()} tooltip={m.tooltip_orbit_data_source()}>
				{#if dataSourceUrl}
					<Link href={dataSourceUrl} external>{dataSourceLabel}</Link>
				{:else}
					{dataSourceLabel}
				{/if}
			</Row>
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
