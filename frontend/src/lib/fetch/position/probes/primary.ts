/**
 * Dynamic primary-body override for probes whose stored fit center isn't the
 * dominant gravitational body at a given jd.
 *
 * The data pipeline stores each probe relative to a single fit center per zone
 * (e.g. `probes/earth-moon` uses Earth, NAIF 399). For position rendering that
 * is fine — `world = fitCenter_world + probe_offset_wrt_fitCenter` is correct
 * regardless of which Earth-system body the probe is actually bound to. The
 * osculating Keplerian elements that drive the orbit line, however, only make
 * physical sense when derived against the dominant primary: an LRO state
 * computed in the Earth frame yields a hyperbolic e≈3.5 / a≈−150 000 km curve
 * because LRO's Earth-relative velocity is the Moon's orbital velocity around
 * Earth plus LRO's velocity around the Moon, well past Earth escape at lunar
 * distance.
 *
 * For the `earth-moon` zone we check if the probe sits inside the Moon's Hill
 * sphere and, when so, retarget the primary to the Moon. Callers translate
 * probe and parent positions and re-derive elements with the Moon's GM —
 * orbit-line geometry then reflects the actual Moon-centric orbit.
 */

import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { chebyshevStateKm } from '$lib/fetch/position/chebyshev/propagate';

/** Lunar Hill sphere radius in km — r_hill = a · (m_moon / 3·m_earth)^(1/3)
 *  with a = 384 400 km and m_moon/m_earth = 1/81.3, ≈ 61 500 km. Probes within
 *  this of the Moon are taken to be gravitationally Moon-bound (LRO, LADEE,
 *  Capstone, Danuri, …); outside it the zone's stored fit center (Earth)
 *  remains the right primary (JWST/L2 halos, ARTEMIS apoapsis, high-Earth
 *  orbits, THEMIS). CR3BP trajectories that cross the boundary (NRHO, halo
 *  orbits at ~70 000 km from Moon) flip parents twice per orbit — neither a
 *  pure Earth nor a pure Moon Kepler curve is right for those anyway. */
const MOON_HILL_RADIUS_KM = 61_500;

/** NAIF ID for Earth's Moon. */
export const MOON_NAIF_ID = 301;

/** Probe primary override at `jd`. Position+velocity of the dominant body
 *  expressed in the same frame as the probe's stored offset (parent-relative
 *  ECLIPJ2000 km, km/day). Null when no override should apply (probe is far
 *  from any candidate moon, or the chebyshev store hasn't loaded Moon yet). */
export interface PrimaryOverride {
	naifId: number;
	positionKm: [number, number, number];
	velocityKmDay: [number, number, number];
}

/**
 * If `fitCenterNaifId` is Earth (399) and the probe sits inside the Moon's
 * Hill sphere, return the Moon's Earth-relative state; else null. Returns null
 * when Moon's or Earth's chebyshev body is unavailable — caller falls back to
 * the stored fit center, which renders incorrectly but won't crash.
 *
 * Both Moon and Earth have the Earth-Moon barycenter (NAIF 3) as their stored
 * chebyshev parent, so their fit-center-relative states need composing:
 *   Moon_wrt_Earth = Moon_wrt_EMB − Earth_wrt_EMB.
 * Using `chebyshevStateKm(moon)` alone would yield Moon_wrt_EMB and offset the
 * Hill-sphere check (and downstream Moon-relative state) by Earth's ~4700 km
 * EMB offset.
 */
export function resolvePrimaryOverride(
	probeOffsetKm: [number, number, number],
	jd: number,
	fitCenterNaifId: number,
	chebStore: ChebyshevStore | null
): PrimaryOverride | null {
	if (fitCenterNaifId !== 399) return null;
	if (!chebStore) return null;
	const moon = chebStore.body(`naif-${MOON_NAIF_ID}`, jd);
	const earth = chebStore.body('naif-399', jd);
	if (!moon || !earth) return null;
	const moonState = chebyshevStateKm(moon, jd);
	const earthState = chebyshevStateKm(earth, jd);
	if (!moonState || !earthState) return null;
	const positionKm: [number, number, number] = [
		moonState.position[0] - earthState.position[0],
		moonState.position[1] - earthState.position[1],
		moonState.position[2] - earthState.position[2]
	];
	const velocityKmDay: [number, number, number] = [
		moonState.velocity[0] - earthState.velocity[0],
		moonState.velocity[1] - earthState.velocity[1],
		moonState.velocity[2] - earthState.velocity[2]
	];
	const dx = probeOffsetKm[0] - positionKm[0];
	const dy = probeOffsetKm[1] - positionKm[1];
	const dz = probeOffsetKm[2] - positionKm[2];
	const distSq = dx * dx + dy * dy + dz * dz;
	if (distSq > MOON_HILL_RADIUS_KM * MOON_HILL_RADIUS_KM) return null;
	return {
		naifId: MOON_NAIF_ID,
		positionKm,
		velocityKmDay
	};
}
