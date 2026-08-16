/**
 * One end of a trip: a body plus, optionally, a site on it.
 *
 * A trajectory is priced against the *body* — mass sets the capture burn,
 * radius the parking orbit, atmosphere the aerocapture discount — and a site
 * only says where you touch down. The one thing a site does decide is the
 * mode: there is no way to arrive at a named crater except by landing there.
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

/** The place on a body an end sits at, once it is known — a named feature to
 *  look up, or bare coordinates, either way a spot on a globe. */
export type EndSite =
	| { kind: 'feature'; featureId: number }
	| { kind: 'point'; latDeg: number; lonDeg: number };
