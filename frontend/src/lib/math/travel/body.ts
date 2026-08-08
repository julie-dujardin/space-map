/**
 * The slice of a body the trajectory model needs. Deliberately narrow so it can
 * be filled from an export detail record, a binary elements row, or a fixture,
 * and so the maths never reaches back into the fetch layer.
 */

import type { OrbitalElements } from '$lib/types/objects';
import { ASSUMED_DENSITY_KG_M3, G_KM3_KG_S2 } from './constants';

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
	 * Surface pressure in bar. Absent means airless for our purposes — the
	 * model only cares whether there is enough atmosphere to brake against.
	 */
	surfacePressureBar?: number;
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
