/** Where the drawer's trip-planner entries lead, and whether there is a trip
 *  to plan at all. Shared by the header button and the overview action row so
 *  both appear on exactly the same objects. */

import { EARTH_ID } from '$lib/constants';
import { navHref } from '$lib/state/focus-link';
import { extrasolarEndAtRest, extrasolarTravelBody } from '$lib/travel/extrasolar-end';
import { transferPlan } from '$lib/travel/travel-body';
import type { AppState } from '$lib/state/app-state.svelte';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { BodyData } from '$lib/types/objects';

export interface TravelEntry {
	href: string;
	/** Null on Earth's own panel: nobody travels to where they already are, so
	 *  the planner opens with the departure unchosen. */
	departure: string | null;
	destination: { id: string; featureId: number | null };
}

/** The planner opened on a trip that ends at `target`. Null where no trip
 *  reaches it, because an entry that leads nowhere is worse than none. For an
 *  object of the extrasolar catalogue, `target` is the body that
 *  {@link extrasolarTripTarget} gives. */
export function travelEntry(
	ctx: ContextManager | undefined,
	appState: AppState | undefined,
	target: BodyData,
	featureId: number | null = null
): TravelEntry | null {
	if (!ctx) return null;
	const departure = target.id === EARTH_ID ? null : EARTH_ID;
	if (departure !== null) {
		// Any bucket, not just majors — that used to hide the entry on every
		// small body and probe, exactly the ones worth planning a trip to.
		const lookup = (id: string) => ctx.getBody(id)?.data;
		const earth = lookup(EARTH_ID);
		if (!earth) return null;
		if (transferPlan(earth, target, lookup).kind === 'blocked') return null;
	}
	const destination = { id: target.id, featureId };
	const href = navHref(appState, departure, destination);
	return href ? { href, departure, destination } : null;
}

/** The body that a trip to an object of the extrasolar catalogue goes to, as
 *  the planner resolves it. A star system gives its primary star. Null when the
 *  planner cannot place the end, or cannot size a planet. */
export async function extrasolarTripTarget(objectId: string): Promise<BodyData | null> {
	const end = await extrasolarEndAtRest(objectId);
	return end && extrasolarTravelBody(end) ? end.body : null;
}
