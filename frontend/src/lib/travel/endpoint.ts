/**
 * One end of a trip.
 *
 * A trajectory is always priced against a *body* — its mass sets the capture
 * burn, its radius the parking orbit, its atmosphere the aerocapture discount.
 * A surface feature does not change any of that; it only says where on the body
 * you touch down. So an endpoint is a body plus, optionally, a place on it.
 *
 * The one thing the feature does decide is the mode: there is no way to arrive
 * at a named crater except by landing in it.
 */

/** What the endpoint picker hands back when a search result is chosen. */
export interface TravelEndpointPick {
	/** The body the trajectory is solved against. A feature's host, or the
	 *  object itself. */
	bodyId: string;
	/** IAU feature id when the pick was a named place on a surface. */
	featureId: number | null;
	/** Localized label, so the field can show it before any bundle is fetched. */
	name: string;
}

/** True when this end is a place on a surface, and so can only be landed on. */
export function isSurfaceEndpoint(featureId: number | null | undefined): boolean {
	return featureId != null;
}
