/**
 * The pieces every timeline needs, whatever it is a timeline of.
 *
 * A trip is legs; a spacecraft's record is what it did. Both are a run of
 * spans on the same clock, drawn as one strip — so where the clock stands in
 * them, and what dates to label the axis with, live here rather than with
 * either subject.
 */

import { dateToJD, jdToDate } from '$lib/format/date';

/** A stretch of time on the strip. An instant has `endJd === startJd`. */
export interface TimelineSpan {
	startJd: number;
	endJd: number;
}

/** Which entry the clock is on: the last one it has reached. Before the first
 *  one that is still the first — "not started yet" is that entry's own state,
 *  not a thing of its own to draw. */
export function entryIndexAt(entries: readonly TimelineSpan[], jd: number): number {
	if (entries.length === 0) return -1;
	let index = 0;
	for (let i = 0; i < entries.length; i++) {
		if (entries[i].startJd <= jd) index = i;
	}
	return index;
}

/** Where a step of `delta` entries lands from `jd`, clamped to the run.
 *  Stepping back from inside a phase means that phase's start, not the entry
 *  before it — the clock is past the entry, not on it. */
export function stepEntryIndex(
	entries: readonly TimelineSpan[],
	jd: number,
	delta: number
): number {
	const at = entryIndexAt(entries, jd);
	if (at < 0) return 0;
	const onEntry = entries[at].startJd === jd;
	const next = delta < 0 && !onEntry ? at : at + delta;
	return Math.min(entries.length - 1, Math.max(0, next));
}

export type TickUnit = 'year' | 'month' | 'day' | 'hour';

export interface AxisTick {
	jd: number;
	/** The boundary the tick sits on, as a calendar date. Carried rather than
	 *  derived back from `jd`: a Date round-tripped through a Julian Date can land
	 *  a millisecond short, and that's enough to mislabel the year. */
	date: Date;
	unit: TickUnit;
}

const YEAR_STEPS = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500] as const;
const MONTH_STEPS = [1, 2, 3, 6] as const;
const DAY_STEPS = [1, 2, 5, 10, 15, 20, 25] as const;
const HOUR_STEPS = [1, 2, 3, 6, 12] as const;

const DAYS_PER_YEAR = 365.25;
const DAYS_PER_MONTH = DAYS_PER_YEAR / 12;
const HOURS_PER_DAY = 24;

/** The finest step from `ladder` that keeps the count under `maxTicks`. */
function stepFor(ladder: readonly number[], span: number, maxTicks: number): number {
	for (const step of ladder) {
		if (span / step <= maxTicks) return step;
	}
	// Past the end of the ladder — a span measured in millennia. Keep decupling
	// the coarsest step rather than drawing hundreds of ticks.
	let step = ladder[ladder.length - 1];
	while (span / step > maxTicks) step *= 10;
	return step;
}

/** Midnight local time on 1 January of `year`. Built by setter, since the Date
 *  constructor maps years under 100 into the 1900s. */
function atYear(year: number): Date {
	const date = new Date(2000, 0, 1);
	date.setFullYear(year, 0, 1);
	date.setHours(0, 0, 0, 0);
	return date;
}

/** Midnight local time on the first of `month` (0-based, may run outside 0-11). */
function atMonth(year: number, month: number): Date {
	const date = atYear(year);
	date.setMonth(month);
	return date;
}

/**
 * Dates to label the axis with, between `startJd` and `endJd`.
 *
 * Aligned to local calendar boundaries rather than even fractions of the
 * span: the labels are read as dates, and a "2035" not sitting on New Year is
 * worse than no tick. Local, not UTC, since that's the clock they're
 * formatted against.
 */
export function axisTicks(startJd: number, endJd: number, maxTicks = 6): AxisTick[] {
	const spanDays = endJd - startJd;
	if (!(spanDays > 0) || !Number.isFinite(spanDays) || maxTicks < 1) return [];

	const start = jdToDate(startJd);
	const end = jdToDate(endJd);
	const ticks: AxisTick[] = [];
	const push = (date: Date, unit: TickUnit) => {
		const jd = dateToJD(date);
		if (jd >= startJd && jd <= endJd) ticks.push({ jd, date, unit });
	};

	// Pick the unit off the spacing the ticks would want, not off the span: at
	// six ticks a 150-day run wants a 25-day step, which is a month rather than
	// a clumsy multiple of a day.
	const stepDays = spanDays / maxTicks;
	if (stepDays >= DAYS_PER_MONTH * 11) {
		const step = stepFor(YEAR_STEPS, spanDays / DAYS_PER_YEAR, maxTicks);
		const first = Math.ceil(start.getFullYear() / step) * step;
		for (let year = first; ; year += step) {
			const date = atYear(year);
			if (date > end) break;
			push(date, 'year');
		}
	} else if (stepDays >= 25) {
		const step = stepFor(MONTH_STEPS, spanDays / DAYS_PER_MONTH, maxTicks);
		// Count months from year zero so alignment doesn't restart each year.
		const startIndex = start.getFullYear() * 12 + start.getMonth();
		for (let index = Math.ceil(startIndex / step) * step; ; index += step) {
			const date = atMonth(Math.floor(index / 12), index % 12);
			if (date > end) break;
			push(date, 'month');
		}
	} else if (stepDays >= 0.5) {
		const step = stepFor(DAY_STEPS, spanDays, maxTicks);
		const date = new Date(start);
		date.setHours(0, 0, 0, 0);
		if (date < start) date.setDate(date.getDate() + 1);
		for (; date <= end; date.setDate(date.getDate() + step)) push(new Date(date), 'day');
	} else {
		const step = stepFor(HOUR_STEPS, spanDays * HOURS_PER_DAY, maxTicks);
		const date = new Date(start);
		date.setMinutes(0, 0, 0);
		while (date < start || date.getHours() % step !== 0) date.setHours(date.getHours() + 1);
		for (; date <= end; date.setHours(date.getHours() + step)) push(new Date(date), 'hour');
	}

	return ticks;
}
