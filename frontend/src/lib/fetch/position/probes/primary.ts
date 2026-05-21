/**
 * Resolve a probe's per-header fit-center override into a state vector
 * relative to the zone's stored fit center.
 *
 * Probe binaries now stamp each probe with its actual gravitational primary
 * (Moon for lunar orbiters, Titan for Cassini at Titan, Vesta for Dawn, …).
 * The render path needs that primary's state in the *zone's* fit-center
 * frame so it can compose `world = zoneCenter_world + (probeOffset - primaryOffset)`
 * and derive orbital elements in the right frame.
 *
 * The compose works as long as the primary and the zone center share a
 * chebyshev parent (Moon & Earth → EMB; Titan & Saturn → Saturn-bary;
 * Vesta & Sun → SSB). That holds for every body the writer can pick today.
 */

import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { chebyshevStateKm } from '$lib/fetch/position/chebyshev/propagate';
import type { Probe } from '$lib/fetch/position/probes/parse';

/** Fit-center body state expressed in the zone's fit-center frame
 *  (ECLIPJ2000, km / km·day⁻¹). */
export interface PrimaryOverride {
	id: string;
	naifId: number;
	positionKm: [number, number, number];
	velocityKmDay: [number, number, number];
}

/**
 * Return the probe's stored fit-center body state in the zone's fit-center
 * frame, or null when the override doesn't apply (probe stayed on the zone
 * center) or when the chebyshev store doesn't yet have the bodies it needs.
 */
export function resolvePrimaryOverride(
	probe: Probe,
	jd: number,
	zoneCenterId: string,
	chebStore: ChebyshevStore | null
): PrimaryOverride | null {
	const fc = probe.fitCenter;
	if (!fc) return null;
	if (fc.id === zoneCenterId) return null;
	if (!chebStore) return null;
	const primary = chebStore.body(fc.id, jd);
	const zoneCenter = chebStore.body(zoneCenterId, jd);
	if (!primary || !zoneCenter) return null;
	if (primary.parentId !== zoneCenter.parentId) {
		// Bodies live in different chebyshev frames — a direct subtract would
		// silently produce a wrong answer. None of today's writer outputs hit
		// this; logging keeps us honest if a future body breaks the invariant.
		console.warn(
			`fit-center override: ${fc.id} (parent ${primary.parentId}) and zone ` +
				`center ${zoneCenterId} (parent ${zoneCenter.parentId}) don't share a ` +
				`chebyshev parent; falling back to zone center`
		);
		return null;
	}
	const primaryState = chebyshevStateKm(primary, jd);
	const zoneCenterState = chebyshevStateKm(zoneCenter, jd);
	if (!primaryState || !zoneCenterState) return null;
	return {
		id: fc.id,
		naifId: primary.naifId,
		positionKm: [
			primaryState.position[0] - zoneCenterState.position[0],
			primaryState.position[1] - zoneCenterState.position[1],
			primaryState.position[2] - zoneCenterState.position[2]
		],
		velocityKmDay: [
			primaryState.velocity[0] - zoneCenterState.velocity[0],
			primaryState.velocity[1] - zoneCenterState.velocity[1],
			primaryState.velocity[2] - zoneCenterState.velocity[2]
		]
	};
}
