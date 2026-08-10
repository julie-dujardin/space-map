/**
 * The two figures the panel shows about being there rather than getting there:
 * how long a message takes, and what it would cost to leave again.
 */

import { SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import {
	departureCost,
	type EndOrbit,
	elementsToState,
	norm,
	sub,
	travelConstants,
	type Route,
	type TravelBody
} from '$lib/math/travel';

/**
 * One-way light time between the two bodies at arrival, in seconds.
 *
 * Uses the real positions on the arrival date, so a slow transfer that lands
 * with the pair on opposite sides of the Sun reports the longer delay it
 * actually has. Returns null when either position is unavailable.
 */
export function signalDelaySeconds(
	origin: TravelBody,
	target: TravelBody,
	arriveJd: number
): number | null {
	const from = elementsToState(origin.elements, arriveJd, travelConstants.GM_SUN_KM3_S2);
	const to = elementsToState(target.elements, arriveJd, travelConstants.GM_SUN_KM3_S2);
	if (!from || !to) return null;
	const separation = norm(sub(to.r, from.r));
	if (!Number.isFinite(separation)) return null;
	return separation / SPEED_OF_LIGHT_KM_S;
}

/**
 * Δv to start the journey home, km/s.
 *
 * Approximate on purpose: it prices leaving the target on a transfer needing
 * the same excess speed the arrival had, which is the right scale but not the
 * true return window's cost. Solving the return properly means a second
 * porkchop, which is a separate trip rather than a statistic.
 *
 * A constant-thrust arc has no such window to leave on, and its cost is not in
 * the escape at all: the way home is the same crossing flown backwards, so it
 * is quoted as the whole of what the outbound spent between the two wells. A
 * spiral is quoted the same way and for the same reason — its escape is a
 * spiral too, and pricing one as an impulsive burn would halve it.
 */
export function returnDvKms(target: TravelBody, route: Route, orbit?: EndOrbit): number {
	if (route.constantThrust || route.lowThrust) return route.inSpaceDvKms;
	const cost = departureCost(
		target,
		route.vInfArrKms,
		route.arrivalMode === 'landing' ? 'surface' : 'orbit',
		// You leave from wherever the arrival left you, so a stationary orbit is
		// as much a term of the way back as it was of the way out.
		orbit
	);
	return cost.ascentKms + cost.injectionKms;
}
