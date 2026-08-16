/** The line under a timeline entry's name. The name itself is the leg's, from
 *  `leg-labels`, so the timeline and the Δv ladder cannot drift apart. */

import { ltrIsolate } from '$lib/format/bidi';
import { formatKm } from '$lib/format/distance';
import { formatDurationNarrow } from '$lib/format/duration';
import * as m from '$lib/paraglide/messages.js';
import { formatDv, formatEndOrbit } from '$lib/travel/format';
import type { TimelineEntry } from '$lib/travel/timeline';

/** Where it happens, what it costs, how long it takes. Figures are isolated
 *  LTR since they sit inline with words, not in their own column — in RTL
 *  they'd otherwise swap ends with their unit. */
export function entryDetail(entry: TimelineEntry): string {
	const parts: string[] = [];
	if (entry.bodyName) parts.push(entry.bodyName);
	if (entry.orbit) {
		parts.push(ltrIsolate(formatEndOrbit(entry.orbit.shape, entry.orbit.bodyRadiusKm)));
	}
	if (entry.altitudeKm !== undefined) parts.push(ltrIsolate(formatKm(entry.altitudeKm)));
	if (entry.dvKms > 0) parts.push(ltrIsolate(formatDv(entry.dvKms)));
	if (entry.days > 0) parts.push(ltrIsolate(formatDurationNarrow(entry.days)));
	if (entry.aerobraked) parts.push(m.travel_aerobraked());
	return parts.join(' · ');
}
