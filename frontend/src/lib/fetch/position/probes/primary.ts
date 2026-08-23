/**
 * Resolve a probe's per-header fit-center override (Moon for lunar orbiters,
 * Titan for Cassini at Titan, …) into a state vector relative to the zone's
 * stored fit center, so the render path can compose
 * `world = zoneCenter_world + (probeOffset - primaryOffset)`. Requires the
 * primary and zone center to share a chebyshev parent — true for every body
 * the writer can pick today.
 */

import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { chebyshevStateKm } from '$lib/fetch/position/chebyshev/propagate';
import type { Probe } from '$lib/fetch/position/probes/parse';
import { IdType } from '$lib/fetch/position/format';
import { getGmKm3s2 } from '$lib/fetch/systems-global';

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
				`chebyshev parent; treating the record as unplaceable`
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

/** The body a probe record's sub-chunks are actually fit against: id for
 *  parenting/position lookups, NAIF id + GM for the propagator. */
export interface ProbePrimary {
	id: string;
	naifId: number;
	muKm3S2: number;
}

/** NAIF id + GM for a fit-center header. Legacy numbered asteroids ship
 *  `spkid = naif + 18e6`, but extended-range NAIF ids (Didymos 20065803)
 *  collide with that window, so the legacy key is tried first and the raw
 *  value is the fallback. Comets share one numbering. */
function spkidPrimary(idValue: number): { naifId: number; muKm3S2: number } {
	const legacy = idValue - 18_000_000;
	if (legacy >= 2_000_000 && legacy <= 2_999_999) {
		const mu = getGmKm3s2(legacy);
		if (mu !== undefined) return { naifId: legacy, muKm3S2: mu };
	}
	return { naifId: idValue, muKm3S2: getGmKm3s2(idValue) ?? 0 };
}

/**
 * Resolve the primary a probe record's sub-chunks are composed against at
 * `jd`: the zone center for plain records, or the stamped fit-center body —
 * via chebyshev (Moon, Titan, Vesta) or, failing that, as a live scene body
 * (`isLive`, for SoA small bodies like Ryugu that have no chebyshev record).
 * Null when the stamped body can't be placed right now. Callers must hide
 * the probe then, never anchor elsewhere: the offset is meaningless against
 * any other body.
 */
export function resolveProbePrimary(
	probe: Probe,
	jd: number,
	zoneCenterNaifId: number,
	chebStore: ChebyshevStore | null,
	isLive?: (id: string) => boolean
): ProbePrimary | null {
	const zoneId = `naif-${zoneCenterNaifId}`;
	const fc = probe.fitCenter;
	if (fc && fc.id !== zoneId) {
		const override = resolvePrimaryOverride(probe, jd, zoneId, chebStore);
		if (override) {
			return {
				id: override.id,
				naifId: override.naifId,
				muKm3S2: getGmKm3s2(override.naifId) ?? 0
			};
		}
		if (isLive?.(fc.id)) {
			if (fc.idType === IdType.SPKID) return { id: fc.id, ...spkidPrimary(fc.idValue) };
			return { id: fc.id, naifId: fc.idValue, muKm3S2: getGmKm3s2(fc.idValue) ?? 0 };
		}
		return null;
	}
	return { id: zoneId, naifId: zoneCenterNaifId, muKm3S2: getGmKm3s2(zoneCenterNaifId) ?? 0 };
}
