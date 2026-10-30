/** The line under a timeline entry's name. The name itself is the leg's, from
 *  `leg-labels`, so the timeline and the Δv ladder cannot drift apart. */

import { ltrIsolate } from '$lib/format/bidi';
import { formatKm } from '$lib/format/distance';
import { formatDurationNarrow } from '$lib/format/duration';
import * as m from '$lib/paraglide/messages.js';
import { formatDegrees } from '$lib/format/quantities';
import { formatDv, formatEndOrbit, shipDuration } from '$lib/travel/format';
import type { TimelineEntry } from '$lib/travel/timeline';

/** Where it happens, what it costs, and how long it takes on each clock.
 *  Figures are isolated LTR because they sit inline with words. Without this,
 *  RTL puts a figure and its unit in the wrong order. */
export function entryDetail(entry: TimelineEntry): string {
	const parts: string[] = [];
	if (entry.bodyName) parts.push(entry.bodyName);
	if (entry.orbit) {
		parts.push(ltrIsolate(formatEndOrbit(entry.orbit.shape, entry.orbit.bodyRadiusKm)));
	}
	if (entry.altitudeKm !== undefined) parts.push(ltrIsolate(formatKm(entry.altitudeKm)));
	if (entry.turnDeg) parts.push(ltrIsolate(formatDegrees(entry.turnDeg)));
	if (entry.dvKms > 0) parts.push(ltrIsolate(formatDv(entry.dvKms)));
	if (entry.absorbedKms) parts.push(ltrIsolate(formatDv(entry.absorbedKms)));
	if (entry.days > 0) parts.push(ltrIsolate(formatDurationNarrow(entry.days)));
	const ship = shipDuration(entry.days, entry.shipDays);
	if (ship) parts.push(m.travel_clock_ship({ value: ltrIsolate(ship) }));
	// The aero legs already say the atmosphere did it in their own names.
	if (entry.aerobraked && entry.kind !== 'aero-pass' && entry.kind !== 'aerobrake') {
		parts.push(m.travel_aerobraked());
	}
	return parts.join(' · ');
}
