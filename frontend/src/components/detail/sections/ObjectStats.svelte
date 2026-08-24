<script lang="ts">
	import { getContext } from 'svelte';
	import * as m from '$lib/paraglide/messages.js';
	import StatCardRow from './kit/StatCardRow.svelte';
	import type { Stat } from './kit/StatCard.svelte';
	import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
	import {
		ObjectType,
		isNaturalBodyType,
		type OrbitalElements,
		type PositionedBody
	} from '$lib/types/objects';
	import { OrbitalSource } from '$lib/fetch/position/format';
	import { isLandedAt, probeStateKm } from '$lib/fetch/position/probes/propagate';
	import { resolveProbePrimary } from '$lib/fetch/position/probes/primary';
	import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
	import { dominantPlanetId, isTopLevelParent } from '$lib/scene/state/bodies.svelte';
	import { currentStateFromElements } from '$lib/math/orbit/state';
	import { diameterKmFromH } from '$lib/math/h-magnitude';
	import { sgp4State } from '$lib/math/orbit/sgp4';
	import { AU_KM, AU_SCALE, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
	import { EARTH_ID } from '$lib/constants';
	import { SECONDS_PER_DAY } from '$lib/time/jd';
	import { formatDistance } from '$lib/format/distance';
	import { formatDuration } from '$lib/format/duration';
	import { formatQuantity } from '$lib/format/quantities';

	const ctx = getContext<ContextManager>('ctx');

	// TLE age past which SGP4's position is worth flagging. A week is roughly
	// where LEO drift becomes visible at map scale; past three weeks the element
	// set is only indicative.
	const ELEMENT_AGE_WARN_DAYS = 7;
	const ELEMENT_AGE_POOR_DAYS = 21;

	interface Props {
		global: GlobalObjectData | null;
		body?: PositionedBody;
		/** TLE-derived elements for earth sats; undefined for probes. */
		orbitElements?: OrbitalElements;
		/** Resolved scene body the orbiter circles (Earth for earth sats). */
		parentBody?: PositionedBody;
		jd: number;
	}
	let { global, body, orbitElements, parentBody, jd }: Props = $props();

	interface FlightStats {
		altitudeKm: number | null;
		speedKms: number | null;
		periodDays: number | null;
		/** One-way light travel time to Earth, in days. Probes only. */
		lightLagDays: number | null;
	}

	let isProbe = $derived(body?.data.orbitalSource === OrbitalSource.SPICE_PROBE);
	// Earth satellites (SGP4 from TLE). These get the card set in place of the
	// altitude/speed/period rows the Orbital table would otherwise show.
	let isEarthSat = $derived(global?.celestrak?.orbit_center === 'earth');

	// The body a moon's elements are measured from: its parent, with a system
	// barycenter (no radius, no usable name) resolved to the dominant planet.
	// Planets borrow their barycenter's heliocentric elements, so they stay on
	// the Sun-relative branch.
	let primary = $derived.by(() => {
		if (body?.data.objectType !== ObjectType.MOON) return undefined;
		const parentId = body.data.parentId;
		if (isTopLevelParent(parentId)) return undefined;
		return ctx?.getBody(dominantPlanetId(parentId) ?? parentId);
	});

	// Mirror the renderer's parent resolution so altitude is measured against the
	// body the probe is fit to (Sun on heliocentric cruise, else planet/moon).
	let probeStats = $derived.by<FlightStats | null>(() => {
		if (!isProbe || !ctx?.probeStore || !body) return null;
		const located = ctx.probeStore.probeWithCenter(body.data.id, jd);
		if (!located) return null;
		// Landed probes get the surface-position section instead.
		if (located.probe.landed && isLandedAt(located.probe, jd)) return null;
		const resolved = resolveProbePrimary(
			located.probe,
			jd,
			located.fitCenterNaifId,
			ctx.chebStore ?? null,
			(id) => ctx.getBody(id) !== undefined
		);
		if (!resolved) return null;
		const state = probeStateKm(located.probe, jd, resolved.muKm3S2);
		if (!state) return null;
		const primary = ctx.getBody(resolved.id) ?? null;
		const rKm = Math.hypot(state.position[0], state.position[1], state.position[2]);
		// probeStateKm velocity is km/day; the cards report km/s.
		const speedKms =
			Math.hypot(state.velocity[0], state.velocity[1], state.velocity[2]) / SECONDS_PER_DAY;
		const radiusKm = primary?.data.radiusKm ?? 0;
		const altitudeKm = radiusKm > 0 && rKm > radiusKm ? rKm - radiusKm : null;
		// Probes report one-way light lag to Earth instead of an orbital period:
		// distance is measured live in scene units (AU_SCALE units per AU).
		const earth = ctx.getBody(EARTH_ID)?.position;
		const p = ctx.getBody(body.data.id)?.position ?? body.position;
		let lightLagDays: number | null = null;
		if (earth && p) {
			const distKm =
				(Math.hypot(p[0] - earth[0], p[1] - earth[1], p[2] - earth[2]) / AU_SCALE) * AU_KM;
			lightLagDays = distKm / SPEED_OF_LIGHT_KM_S / SECONDS_PER_DAY;
		}
		return { altitudeKm, speedKms, periodDays: null, lightLagDays };
	});

	let earthSatStats = $derived.by<FlightStats | null>(() => {
		if (isProbe || !isEarthSat || !body || !parentBody) return null;
		if (!(parentBody.data.radiusKm > 0)) return null;
		const state = body.data.satrec
			? sgp4State(body.data.satrec, jd)
			: orbitElements
				? currentStateFromElements(orbitElements, jd)
				: null;
		if (!state) return null;
		const altitudeKm = state.rKm - parentBody.data.radiusKm;
		const periodMin = global?.celestrak?.period;
		return {
			altitudeKm: altitudeKm > 0 ? altitudeKm : null,
			speedKms: state.vKms,
			periodDays: periodMin != null ? periodMin / 1440 : null,
			lightLagDays: null
		};
	});

	let stats = $derived(probeStats ?? earthSatStats);

	// How stale the TLE driving this satellite is. Snapshots are weekly, and a
	// week a satellite went untracked is filled from a neighbouring one up to 30
	// days out, so a visible age means the position is propagated further than
	// SGP4 stays trustworthy. Only surfaced once it degrades — see `cards`.
	let elementAgeDays = $derived(
		isEarthSat && orbitElements?.epoch != null ? Math.abs(jd - orbitElements.epoch) : null
	);

	// Glanceable trio for natural bodies, each block first-available: a physical
	// magnitude, orbital speed, then rotation period (falling back to a live
	// distance). Full figures still live in the Physical/Orbital panels below.
	let bodyCards = $derived.by<Stat[]>(() => {
		if (isProbe || isEarthSat || !body || !isNaturalBodyType(global?.type)) return [];
		const out: Stat[] = [];
		const sbdb = global?.sbdb;
		const wd = global?.wikidata;
		const radii = global?.radii;

		// Block 1 — a size, in kilometres. Wikidata's mass unit varies by source
		// and reads as noise at a glance, so mass only stands in when no size is
		// measured at all. Triaxial bodies average their axes; per-axis figures
		// live in the Physical panel.
		const diameterKm =
			sbdb?.diameter ?? (radii ? ((radii.a + radii.b + radii.c) / 3) * 2 : undefined);
		if (diameterKm != null)
			out.push({
				label: m.diameter(),
				value: formatQuantity({ value: diameterKm, unit: 'kilometre' }, true)
			});
		else if (wd?.radius)
			out.push({
				label: m.diameter(),
				value: formatQuantity({ value: wd.radius.value * 2, unit: wd.radius.unit }, true)
			});
		else if (sbdb?.H != null)
			// No measured size: the H-magnitude estimate, as in the Physical panel.
			out.push({
				label: m.diameter(),
				value: formatQuantity(
					{ value: diameterKmFromH(sbdb.H, sbdb.albedo ?? undefined), unit: 'kilometre' },
					true
				),
				tooltip: m.tooltip_diameter_estimated()
			});
		else if (sbdb?.mass ?? wd?.mass)
			out.push({
				label: m.property_name_mass(),
				value: formatQuantity((sbdb?.mass ?? wd?.mass)!)
			});

		// Block 2 — orbital speed via vis-viva from the body's own elements.
		// Skipped for the central star: its only motion is the barycentric wobble.
		const state = orbitElements ? currentStateFromElements(orbitElements, jd) : null;
		if (state && body.data.objectType !== ObjectType.STAR)
			out.push({
				label: m.orbital_speed(),
				value: formatQuantity({ value: state.vKms, unit: 'kilometre_per_second' }, true),
				tooltip: m.tooltip_orbital_speed()
			});

		// Block 3 — rotation period, else a live distance. `state.rKm` is measured
		// from whatever the elements orbit, so only Sun/SSB orbiters are truly
		// heliocentric; everything else reports altitude over its primary, or
		// distance to it when no radius is known.
		const w1 = global?.orientation?.w1;
		const rotationPeriodDays = w1 ? 360 / Math.abs(w1) : sbdb?.rot_per ? sbdb.rot_per / 24 : null;
		if (rotationPeriodDays != null)
			out.push({
				label: m.rotation_period(),
				value: formatDuration(rotationPeriodDays),
				tooltip: m.tooltip_rotation_period()
			});
		else if (state && !primary)
			out.push({
				label: m.distance_from_sun(),
				value: formatDistance(state.rKm / AU_KM),
				tooltip: m.tooltip_distance_from_sun()
			});
		else if (state && primary) {
			const altitudeKm = state.rKm - primary.data.radiusKm;
			if (primary.data.radiusKm > 0 && altitudeKm > 0)
				out.push({
					label: m.altitude(),
					value: formatDistance(altitudeKm / AU_KM),
					tooltip: m.tooltip_altitude()
				});
			else if (primary.data.name)
				out.push({
					label: m.distance_from_body({ name: primary.data.name }),
					value: formatDistance(state.rKm / AU_KM),
					tooltip: m.tooltip_distance_from_body({ name: primary.data.name })
				});
		}
		// Position accuracy from the SBDB condition code (U parameter, 0 best to
		// 9 worst), bucketed so the quality reads at a glance. Keeps the trio a
		// trio: rather than a 4th card, it takes block 3's slot.
		const cc = sbdb?.condition_code;
		if (cc != null) {
			if (out.length >= 3) out.pop();
			const [value, dot] =
				cc <= 2
					? [m.position_accuracy_high(), 'bg-emerald-400']
					: cc <= 5
						? [m.position_accuracy_medium(), 'bg-amber-400']
						: [m.position_accuracy_low(), 'bg-rose-400'];
			out.push({
				label: m.position_accuracy(),
				value,
				tooltip: m.tooltip_position_accuracy({ code: cc }),
				dot
			});
		}
		return out;
	});

	let cards = $derived.by<Stat[]>(() => {
		const s = stats;
		if (!s) return bodyCards;
		const out: Stat[] = [];
		if (s.altitudeKm != null)
			out.push({
				label: m.altitude(),
				value: formatDistance(s.altitudeKm / AU_KM),
				tooltip: m.tooltip_altitude()
			});
		if (s.speedKms != null)
			out.push({
				label: m.orbital_speed(),
				value: formatQuantity({ value: s.speedKms, unit: 'kilometre_per_second' }, true),
				tooltip: m.tooltip_orbital_speed()
			});
		if (s.periodDays != null)
			out.push({
				label: m.orbital_period(),
				value: formatDuration(s.periodDays),
				tooltip: m.tooltip_orbital_period()
			});
		if (s.lightLagDays != null)
			out.push({
				label: m.light_lag(),
				value: formatDuration(s.lightLagDays),
				tooltip: m.tooltip_light_lag()
			});
		// Stale elements take the third card's slot (orbital period), matching how
		// the small-body condition code displaces one rather than adding a fourth.
		// No card while the elements are fresh: an always-green tile trains the eye
		// to skip it, and the accurate case is the overwhelming majority.
		const age = elementAgeDays;
		if (age != null && age > ELEMENT_AGE_WARN_DAYS) {
			if (out.length >= 3) out.splice(2, 1);
			out.push({
				label: m.position_accuracy(),
				value:
					age > ELEMENT_AGE_POOR_DAYS ? m.position_accuracy_low() : m.position_accuracy_medium(),
				tooltip: m.tooltip_position_accuracy_element_age({ age: formatDuration(age) }),
				dot: age > ELEMENT_AGE_POOR_DAYS ? 'bg-rose-400' : 'bg-amber-400'
			});
		}
		return out;
	});
</script>

<StatCardRow stats={cards} />
