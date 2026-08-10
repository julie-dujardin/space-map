/**
 * Cache keys for the derived views of a route — the drawn geometry, the hazard
 * scan, the timeline.
 *
 * The solve effect re-runs several times a second and hands back a fresh (and
 * usually identical) route object each time; rebuilding a few hundred
 * propagated points or a six-route hazard scan off every one of those would be
 * work nobody asked for. So each view is keyed on what actually shapes it, and
 * only a change in the key rebuilds. The flip side is the contract these keys
 * carry: anything a view reads off the route MUST be in its key, or a re-solve
 * that changes only that input leaves the view showing the previous trip's.
 */

import { routeEndJd, type EndOrbit, type Route, type TravelBody } from '$lib/math/travel';
import type { TransferFrame } from '$lib/travel/travel-body';

/** The orbit an end was priced at, as a key fragment. */
function orbitEcho(orbit?: EndOrbit): string {
	return orbit ? `${orbit.rPeriKm}/${orbit.rApoKm}` : '';
}

/** What shapes the drawn arc: the crossing itself, and the end-orbit rings,
 *  which are sized off the orbits the route was priced at. */
export function routeKey(route: Route, center: string, transfer: TransferFrame): string {
	const via = route.flybys?.[0];
	return [
		center,
		route.departureId,
		route.targetId,
		route.departJd,
		route.tofDays,
		route.departureMode,
		route.arrivalMode,
		orbitEcho(route.departureOrbit),
		orbitEcho(route.targetOrbit),
		route.constantThrust ?? '',
		route.lowThrust?.accelMs2 ?? '',
		via ? `${via.bodyId}@${via.jd}` : '',
		transfer.systemPrimary ?? '',
		transfer.centralMu ?? ''
	].join('|');
}

/**
 * What the hazard scan reads beyond the geometry: the entry speed the
 * atmospheric hazard is graded on, and the campaign it spans.
 *
 * Both keyed as the priced figures rather than as the request that produced
 * them — the same `aero` prices airless until the detail bundle lands, and a
 * re-solve that only learned about the air moves none of the dates above.
 */
export function hazardKey(route: Route, center: string, transfer: TransferFrame): string {
	return [routeKey(route, center, transfer), route.entrySpeedKms ?? '', routeEndJd(route)].join(
		'|'
	);
}

/** What the timeline draws: the legs in time with their Δv, bracketed by the
 *  orbits at the two ends where those ends are orbits. */
export function timelineKey(
	route: Route,
	originName: string | null,
	targetName: string | null,
	bodies: { departure: TravelBody; target: TravelBody } | null
): string {
	return [
		route.departureId,
		route.targetId,
		route.departJd,
		route.arriveJd,
		// The campaign after the crossing, and every burn's price — either can
		// change without moving the dates above, and both are drawn.
		routeEndJd(route),
		route.totalDvKms,
		route.departureMode,
		route.arrivalMode,
		orbitEcho(route.departureOrbit),
		orbitEcho(route.targetOrbit),
		route.constantThrust ?? '',
		route.lowThrust?.accelMs2 ?? '',
		(route.flybys ?? []).map((flyby) => `${flyby.bodyId}@${flyby.jd}`).join(','),
		originName ?? '',
		targetName ?? '',
		// The orbits at the two ends are sized off the bodies, which arrive with
		// a fetched bundle: without this the timeline built before they land
		// would keep its missing ends for the rest of the trip.
		bodies ? `${bodies.departure.radiusKm}/${bodies.target.radiusKm}` : ''
	].join('|');
}
