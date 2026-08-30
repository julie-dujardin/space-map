/**
 * A spacecraft's curated record as the strip along the map draws it.
 *
 * The record is already in order and already dated, so there is no arithmetic
 * to do: each event is a moment, each span a stretch. What this adds is the
 * one thing the strip can't know — that a third of the events happened
 * outside the craft's own ephemeris, where the map has nowhere to draw it.
 * Those are marked rather than moved: Galileo launched in 1989 whether or not
 * a kernel covers the year.
 */

import * as m from '$lib/paraglide/messages.js';
import type { ProbeCoverage } from '$lib/fetch/metadata';
import type { ProbeEvent } from '$lib/fetch/objects/object-data';
import type { TimelineSpan } from '$lib/timeline/axis';
import type { StripItem } from '$lib/timeline/strip';
import { eventDay, eventLabel, eventPlace, flybyPurposeLabel } from './event-labels';

/** The spans the craft can be drawn in. */
function coverageWindows(coverage: ProbeCoverage): [number, number][] {
	return coverage.windows ?? [[coverage.start_jd, coverage.end_jd]];
}

/** Whether the craft has a trajectory at this date. Coverage bounds are
 *  whole-day-ish, so a same-day event is left alone. */
function outsideCoverage(jd: number, coverage: ProbeCoverage | undefined): boolean {
	if (!coverage) return false;
	return !coverageWindows(coverage).some(([from, to]) => jd >= from - 0.5 && jd <= to + 0.5);
}

/** The stretches of `[startJd, endJd]` the craft cannot be drawn in: before
 *  the archive starts, after it ends, and every hole inside it. */
export function coverageGaps(
	coverage: ProbeCoverage | undefined,
	startJd: number,
	endJd: number
): TimelineSpan[] {
	if (!coverage) return [];
	const gaps: TimelineSpan[] = [];
	let cursor = startJd;
	for (const [from, to] of coverageWindows(coverage)) {
		if (from > cursor) gaps.push({ startJd: cursor, endJd: Math.min(from, endJd) });
		cursor = Math.max(cursor, to);
		if (cursor >= endJd) break;
	}
	if (cursor < endJd) gaps.push({ startJd: cursor, endJd });
	return gaps.filter((g) => g.endJd > g.startJd);
}

export function eventStripItems(
	events: readonly ProbeEvent[],
	coverage?: ProbeCoverage
): StripItem[] {
	return events.map((event, index) => {
		const purpose = flybyPurposeLabel(event);
		const place = eventPlace(event);
		return {
			// The date alone repeats — two burns can share a day — so the position
			// in the record is what makes it this event and not the other.
			id: `${index}-${event.type}-${event.date}`,
			label: eventLabel(event),
			when: eventDay(event),
			detail: [place || undefined, purpose].filter(Boolean).join(' · ') || undefined,
			startJd: event.jd,
			endJd: event.end_jd ?? event.jd,
			isPhase: event.end_jd !== undefined,
			note: outsideCoverage(event.jd, coverage) ? m.probe_timeline_untracked() : undefined
		};
	});
}
