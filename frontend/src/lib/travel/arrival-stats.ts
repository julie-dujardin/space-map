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

/** One-way light time between the two ends at arrival, seconds. Inside the
 *  solar system it uses the positions on the arrival date, because the Sun can
 *  be between the two ends then. Between stars it is the distance between them. */
export function signalDelaySeconds(
	origin: TravelBody,
	target: TravelBody,
	route: Route
): number | null {
	if (route.interstellar) return route.interstellar.distanceKm / SPEED_OF_LIGHT_KM_S;
	const from = elementsToState(origin.elements, route.arriveJd, travelConstants.GM_SUN_KM3_S2);
	const to = elementsToState(target.elements, route.arriveJd, travelConstants.GM_SUN_KM3_S2);
	if (!from || !to) return null;
	const separation = norm(sub(to.r, from.r));
	if (!Number.isFinite(separation)) return null;
	return separation / SPEED_OF_LIGHT_KM_S;
}

/**
 * Δv to start the journey home, km/s.
 *
 * This is an estimate. It prices a departure at the same excess speed as the
 * arrival. The true cost needs a second porkchop for the return window.
 *
 * A held arc, a spiral and a crossing between stars have no window. The return
 * is the same trip flown back, so it costs the whole outbound spend.
 */
export function returnDvKms(target: TravelBody, route: Route, orbit?: EndOrbit): number {
	if (route.constantThrust || route.lowThrust || route.interstellar) return route.inSpaceDvKms;
	const cost = departureCost(
		target,
		route.vInfArrKms,
		route.arrivalMode === 'landing' ? 'surface' : 'orbit',
		// You leave from wherever the arrival left you.
		orbit
	);
	return cost.ascentKms + cost.injectionKms;
}
