/**
 * Which Earth-orbit zone pages a trip can be planned to, and the orbit each
 * one is met in.
 *
 * A zone is a region, not an orbit, so it is navigable only where the planner
 * already prices an orbit that lands inside it — the mapping is checked against
 * `classifyEarthOrbit` in `orbit-zone-target.test.ts` rather than asserted here.
 *
 * A zone the named orbits miss goes to the custom orbit, opened inside the zone
 * and movable from there: a shape inside it, and for an inclination band the
 * plane too, since the custom orbit is the one that is shaped at all.
 *
 * That leaves out only the zones no offered orbit reaches: the one beyond what
 * Earth holds — a third of the Hill radius stops 8000 km short of the 500000 km
 * VHEO begins at — and the Lagrange points, which are not orbits about Earth.
 */

import { CLASS_SLUG_PREFIX, GEO_ALT_KM } from '$lib/charts/orbit-zones';
import type { EndpointMode } from './trip';

/** How a zone is arrived at: the mode, and for `custom` the two altitudes that
 *  put the orbit inside the zone and the plane that puts it in the band. An
 *  apoapsis left off is the periapsis, which is a circular orbit. */
export interface OrbitZoneTarget {
	mode: EndpointMode;
	altKm?: number;
	apoAltKm?: number;
	incDeg?: number;
	/** Where periapsis sits, degrees round from the equator crossing. What hangs
	 *  a Molniya's apogee over the north rather than over the equator. */
	argPeriDeg?: number;
}

/**
 * Zone class name → the arrival that lands there.
 *
 * The stationary belt splits three ways over one orbit, on plane alone: GEO is
 * the equatorial one the named orbit already is, while GSO in whatever plane and
 * IGSO in an inclined one go to the custom orbit at the same altitude.
 */
export const ZONE_TARGETS: Record<string, OrbitZoneTarget> = {
	VLEO: { mode: 'low-orbit' },
	// No named orbit sits between 600 and 2000 km, so the zone is met on the
	// custom orbit, opened at an altitude inside it and movable from there.
	LEO: { mode: 'custom', altKm: 1000 },
	MEO: { mode: 'semi-sync' },
	GSO: { mode: 'custom', altKm: GEO_ALT_KM },
	GEO: { mode: 'stationary' },
	// Every inclined synchronous orbit is one, from QZSS at 43° to BeiDou at 55°.
	IGSO: { mode: 'custom', altKm: GEO_ALT_KM, incDeg: 45 },
	GTO: { mode: 'transfer' },
	// The eccentric shapes, each opened on the orbit it is named after. Molniya
	// and Tundra are the same 63.4° plane that holds an apogee still, and both
	// put that apogee three quarters of a turn from the equator crossing, which
	// is what parks it over the northern hemisphere they were flown to serve.
	// The plain HEO names neither, since nothing but its shape makes it one.
	HEO: { mode: 'custom', altKm: 1000, apoAltKm: 47000 },
	MOL: { mode: 'custom', altKm: 600, apoAltKm: 39750, incDeg: 63.4, argPeriDeg: 270 },
	TUN: { mode: 'custom', altKm: 27400, apoAltKm: 44200, incDeg: 63.4, argPeriDeg: 270 },
	// Clear of the stationary belt by more than the 200 km that defines the
	// graveyard, close enough to still be it rather than a high orbit.
	GRA: { mode: 'custom', altKm: GEO_ALT_KM + 300 },
	HIGH: { mode: 'custom', altKm: 100000 },
	CIS: { mode: 'heo' },
	// The inclination bands, at the altitude their 2000 km apogee limit leaves
	// them. Sun-synchronous is opened at the plane a low orbit is sun-synchronous
	// in, which the planner takes as a plane like any other — it prices the turn
	// into it, not the precession that makes it worth flying.
	EQU: { mode: 'custom', altKm: 800, incDeg: 0 },
	POL: { mode: 'custom', altKm: 800, incDeg: 90 },
	SSO: { mode: 'custom', altKm: 800, incDeg: 98 },
	RET: { mode: 'custom', altKm: 800, incDeg: 120 }
};

/** The arrival a `class-` page offers, or null where the planner has none. */
export function orbitZoneTarget(slug: string): OrbitZoneTarget | null {
	if (!slug.startsWith(CLASS_SLUG_PREFIX)) return null;
	return ZONE_TARGETS[slug.slice(CLASS_SLUG_PREFIX.length)] ?? null;
}
