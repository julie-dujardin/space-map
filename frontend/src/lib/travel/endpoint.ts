/**
 * One end of a trip.
 *
 * A trajectory is always priced against a *body* — its mass sets the capture
 * burn, its radius the parking orbit, its atmosphere the aerocapture discount.
 * A place on that body does not change any of that; it only says where you
 * touch down. So an endpoint is a body plus, optionally, a site on it.
 *
 * The one thing a site does decide is the mode: there is no way to arrive at a
 * named crater, or at a lander parked in one, except by landing there.
 */

import type { NavPlace } from '$lib/state/view';

/** What the endpoint picker hands back when a search result is chosen. */
export interface TravelEndpointPick {
	/** The body the trajectory is solved against. A feature's host, or the
	 *  object itself. */
	bodyId: string;
	/** IAU feature id when the pick was a named place on a surface. */
	featureId: number | null;
	/** Coordinates when the pick was a place nothing names — a launch pad. */
	place?: NavPlace | null;
	/** Localized label, so the field can show it before any bundle is fetched. */
	name: string;
}

/**
 * The place on a body an end sits at, once it is known.
 *
 * A feature is named and has to be looked up; a landed probe carries its own
 * coordinates out of the position stream, and a launch pad has nothing but
 * coordinates to be. All of them come down to a spot on a globe, which is all
 * the trajectory ever wanted.
 */
export type EndSite =
	| { kind: 'feature'; featureId: number }
	| { kind: 'point'; latDeg: number; lonDeg: number };
