/**
 * Which Earth-orbit zone pages a trip can be planned to, and the orbit each
 * one is met in.
 *
 * A zone is a region, not an orbit, so it is navigable only where the planner
 * already prices an orbit that lands inside it — the mapping is checked
 * against `classifyEarthOrbit` in `orbit-zone-target.test.ts` rather than
 * asserted here. That leaves out the zones whose orbits the kernel doesn't
 * hold: the inclination bands (a polar or sun-synchronous orbit costs what any
 * circular orbit at that altitude does), the Lagrange points, and the shapes
 * no offered orbit reaches.
 */

import { CLASS_SLUG_PREFIX } from '$lib/charts/orbit-zones';
import type { EndpointMode } from './trip';

/** How a zone is arrived at: the mode, and for `custom` the altitude that puts
 *  the circular orbit inside the zone. */
export interface OrbitZoneTarget {
	mode: EndpointMode;
	altKm?: number;
}

/**
 * Zone class name → the arrival that lands there.
 *
 * GEO shares the stationary orbit with GSO: the model prices a period, not a
 * plane, so the two differ by an inclination it never charges for.
 */
export const ZONE_TARGETS: Record<string, OrbitZoneTarget> = {
	VLEO: { mode: 'low-orbit' },
	// No named orbit sits between 600 and 2000 km, so the zone is met on the
	// custom orbit, opened at an altitude inside it and movable from there.
	LEO: { mode: 'custom', altKm: 1000 },
	MEO: { mode: 'semi-sync' },
	GSO: { mode: 'stationary' },
	GEO: { mode: 'stationary' },
	GTO: { mode: 'transfer' },
	CIS: { mode: 'heo' }
};

/** The arrival a `class-` page offers, or null where the planner has none. */
export function orbitZoneTarget(slug: string): OrbitZoneTarget | null {
	if (!slug.startsWith(CLASS_SLUG_PREFIX)) return null;
	return ZONE_TARGETS[slug.slice(CLASS_SLUG_PREFIX.length)] ?? null;
}
