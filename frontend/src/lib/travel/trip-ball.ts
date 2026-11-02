/**
 * What a trip at another star covers, for the camera that opens on it. The planner
 * has no route yet at that moment, so this reads the ends and the terms of the link.
 *
 * Only a custom orbit is wider than a few radii of its body. A body's other orbits
 * stay inside the capture ellipse.
 */

import { SUN_ID } from '$lib/constants';
import { CAPTURE_APOAPSIS_RADII } from '$lib/math/travel/constants';
import { AU_KM } from '$lib/math/units';
import { systemOf } from '$lib/state/nav-end';
import type { BodyData } from '$lib/types/objects';
import type { TripEnd, TripState } from './trip';

/** A ball that holds a whole trip. */
export interface TripBall {
	/** The body at its centre. */
	centerId: string;
	radiusKm: number;
}

function radiusOf(body: BodyData): number {
	return Number.isFinite(body.radiusKm) ? body.radiusKm : 0;
}

/** How far the orbits of `end` reach from `body`, km. */
function orbitsReachKm(body: BodyData, end: TripEnd): number {
	const radiusKm = radiusOf(body);
	return end.mode === 'custom'
		? radiusKm + Math.max(end.altKm, end.apoAltKm)
		: CAPTURE_APOAPSIS_RADII * radiusKm;
}

/** The ball that holds a trip at another star. It stays about the one body of a
 *  change of orbit, and else about the star, out to the far end of a planet's
 *  orbit. Null for a trip of the solar system, or between two systems, and for a
 *  trip with no size. */
export function tripBall(from: BodyData, to: BodyData, trip: TripState): TripBall | null {
	const star = systemOf(to.id);
	if (star === SUN_ID || systemOf(from.id) !== star) return null;
	const { origin, target } = trip.ends;
	const reachOf = (body: BodyData, end: TripEnd) =>
		from.id === to.id || body.id === star
			? orbitsReachKm(body, end)
			: body.a * (1 + body.e) * AU_KM;
	const radiusKm = Math.max(reachOf(from, origin), reachOf(to, target));
	if (!(radiusKm > 0)) return null;
	return { centerId: from.id === to.id ? to.id : star, radiusKm };
}

/** The widest custom orbit at a star end of a trip, km. Zero with none. */
export function starRingKm(from: BodyData, to: BodyData, trip: TripState): number {
	const ringOf = (body: BodyData, end: TripEnd) =>
		end.mode === 'custom' && systemOf(body.id) === body.id ? orbitsReachKm(body, end) : 0;
	return Math.max(ringOf(from, trip.ends.origin), ringOf(to, trip.ends.target));
}
