/**
 * Cache keys for the derived views of a route — drawn geometry, hazard scan,
 * timeline.
 *
 * The solve effect re-runs several times a second with a fresh (often
 * identical) route object, so each view is keyed on what actually shapes it
 * and only rebuilds on a change. The contract: anything a view reads off the
 * route MUST be in its key, or a re-solve can leave it showing the previous
 * trip's.
 */

import { routeEndJd, type EndOrbit, type Route, type TravelBody } from '$lib/math/travel';
import type { DrawnDates } from '$lib/travel/timeline';
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
		transfer.orbitChange ?? '',
		transfer.centralMu ?? ''
	].join('|');
}

/**
 * What the hazard scan reads beyond the geometry: entry speed and the
 * campaign span, keyed as priced figures rather than the request that
 * produced them — the same `aero` prices airless until the detail bundle
 * lands, and none of the dates above move when a re-solve only learns of it.
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
	bodies: { departure: TravelBody; target: TravelBody } | null,
	/** The geometry's own dates, which land after the legs do and re-date the
	 *  cards the drawing knows better when they do. */
	drawn?: DrawnDates | null
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
		// End orbits are sized off the bodies, which arrive with a fetched bundle
		// — without this, a timeline built before they land keeps missing ends.
		bodies ? `${bodies.departure.radiusKm}/${bodies.target.radiusKm}` : '',
		[drawn?.liftoffJd, drawn?.touchdownJd, drawn?.cruiseJd, drawn?.captureJd, drawn?.raiseJd]
			.map((date) => date ?? '')
			.join('/')
	].join('|');
}
