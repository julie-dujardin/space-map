/**
 * A probe that is sitting on something, as a trip end.
 *
 * A landed probe has no orbit to transfer to — it has a place on a body that
 * does. So an end naming one is priced against the body it came down on and
 * flown to the spot it is parked at, which is the end a named crater already
 * is. The spot comes off the position stream the renderer already places the
 * probe with, so the trip lands where the probe is drawn.
 *
 * Only a phase nothing flies after counts. A probe that lifted off again, or
 * whose capsule was recovered, was in that place for a window rather than
 * being there — and a trip is planned for whenever the reader likes.
 */

import type { ProbeStore } from '$lib/fetch/position/probes/store';
import { landedOpenEnded, landedPositionAt } from '$lib/fetch/position/probes/propagate';

/** Where a landed probe is: the body it is on, and where on it. */
export interface LandedEnd {
	/** The body the trip is actually priced against. */
	hostId: string;
	latDeg: number;
	lonDeg: number;
}

/**
 * The place a probe is parked at, or null when it is not parked — flying, out
 * of the loaded window, or landed only for a while.
 *
 * `jd` places the read rather than dating the answer: the site is body-fixed
 * and the probe is not going anywhere, so the caller can hold what comes back
 * for the whole trip however far out it lands.
 */
export function landedEnd(
	store: ProbeStore | null | undefined,
	id: string,
	jd: number
): LandedEnd | null {
	if (!store || !id.startsWith('probe-')) return null;
	const probe = store.probeWithCenter(id, jd)?.probe;
	if (!probe?.landed || !landedOpenEnded(probe)) return null;
	const site = landedPositionAt(probe.landed, jd, true);
	if (!site) return null;
	return { hostId: `naif-${probe.landed.bodyNaifId}`, latDeg: site.latDeg, lonDeg: site.lngDeg };
}
