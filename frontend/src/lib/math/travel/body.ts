/**
 * The slice of a body the trajectory model needs. Deliberately narrow so it can
 * be filled from an export detail record, a binary elements row, or a fixture,
 * and so the maths never reaches back into the fetch layer.
 */

import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import { ASSUMED_DENSITY_KG_M3, G_KM3_KG_S2, SEC_PER_DAY } from './constants';

export interface TravelBody {
	/** Prefixed object id, e.g. "naif-499". */
	id: string;
	/** Gravitational parameter, km³/s². */
	mu: number;
	/** True when `mu` came from assumed density rather than a measurement. */
	muEstimated: boolean;
	/** Mean radius, km. */
	radiusKm: number;
	/** Elements placing the body about its primary. */
	elements: OrbitalElements;
	/**
	 * Surface pressure in bar. Absent means there is no reading at a surface —
	 * either because the body is airless, or because it has no surface for one to
	 * be taken at. What ascent and landing are priced against.
	 */
	surfacePressureBar?: number;
	/**
	 * True when there is an envelope to fly a braking pass through, whether or
	 * not anything can stand under it. Separate from the pressure above because
	 * the giants are the best aerocapture targets in the literature and the worst
	 * places to quote a surface: a pressure at their cloud tops is not a surface
	 * reading, but it is still an atmosphere.
	 */
	hasAtmosphere?: boolean;
	/** Primary this body orbits; absent for heliocentric bodies. */
	parentId?: string;
}

/**
 * GM from a radius and an assumed bulk density — the fallback for the small
 * bodies that make up most of the catalogue, where no mass has been measured.
 * At these scales capture and landing costs are metres per second either way,
 * so the error never moves a route decision; callers surface it as an estimate
 * rather than hiding it.
 */
export function estimateMu(radiusKm: number, densityKgM3 = ASSUMED_DENSITY_KG_M3): number {
	const volumeKm3 = (4 / 3) * Math.PI * radiusKm ** 3;
	return G_KM3_KG_S2 * densityKgM3 * 1e9 * volumeKm3;
}

/**
 * μ of whatever a body goes round, km³/s², from Kepler's third law.
 *
 * A satellite's own period and distance name the mass at the focus, so a pair of
 * moons can price a transfer about their planet without anyone having to look the
 * planet up. Agrees with a measured GM to about the seven digits the packed mean
 * motion carries, since that is what it was fitted against.
 */
export function muFromElements(el: OrbitalElements): number {
	const nRadPerSec = (el.n * (Math.PI / 180)) / SEC_PER_DAY;
	const aKm = el.a * AU_KM;
	return nRadPerSec * nRadPerSec * aKm ** 3;
}

/** Surface escape velocity, km/s. */
export function escapeSpeed(body: TravelBody): number {
	return Math.sqrt((2 * body.mu) / body.radiusKm);
}

/**
 * Radius of the sphere of influence, km — where the body's pull overtakes its
 * primary's. Bounds where a patched-conic leg is meaningful.
 */
export function sphereOfInfluenceKm(body: TravelBody, primaryMu: number, aKm: number): number {
	if (!(primaryMu > 0) || !(aKm > 0)) return Infinity;
	return aKm * Math.pow(body.mu / primaryMu, 0.4);
}
