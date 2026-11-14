/**
 * The pieces every timeline needs, whatever it is a timeline of.
 *
 * A trip is legs; a spacecraft's record is what it did. Both are a run of
 * spans on the same clock, drawn as one strip — so where the clock stands in
 * them, and what dates to label the axis with, live here rather than with
 * either subject.
 */

import { dateToJD, jdToDate, LAST_DATE_JD } from '$lib/time/jd';
import { GREGORIAN_STRUCTURED, type CalendarId } from '$lib/time/calendars';
import { scannerFor } from '$lib/time/calendars/scan';
import { dateToJdn, jdnToLocalMidnight } from '$lib/time/calendars/day-number';

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
/** Past this many months to a tick, ticks go to years: a tick every five
 *  years labelled with the month it falls in says nothing. */
const MAX_MONTHS_PER_TICK = MONTH_STEPS[MONTH_STEPS.length - 1];
const DAY_STEPS = [1, 2, 5, 10, 15, 20, 25] as const;
const HOUR_STEPS = [1, 2, 3, 6, 12] as const;
const DECIMAL_HOUR_STEPS = [1, 2, 5] as const;

const DAYS_PER_YEAR = 365.25;
const DAYS_PER_MONTH = DAYS_PER_YEAR / 12;
const HOURS_PER_DAY = 24;
const DECIMAL_HOURS_PER_DAY = 10;

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
 * formatted against. The boundaries are the reader's calendar's: a Hijri
 * year starts where it does, not on 1 January.
 */
export function axisTicks(
	startJd: number,
	endJd: number,
	maxTicks = 6,
	calendar: CalendarId = 'gregory',
	/** Hours of the Republic's decimal day: ten to the day, each 2.4 of ours. */
	decimalTime = false
): AxisTick[] {
	const spanDays = endJd - startJd;
	if (!(spanDays > 0) || !Number.isFinite(spanDays) || maxTicks < 1) return [];
	const eraStart = GREGORIAN_STRUCTURED.get(calendar);
	if (eraStart === undefined) {
		return calendarTicks(startJd, endJd, maxTicks, calendar, decimalTime);
	}

	const start = jdToDate(startJd);
	// Past the range of `Date` there is no calendar to tick.
	const end = jdToDate(Math.min(endJd, LAST_DATE_JD));
	const ticks: AxisTick[] = [];
	const push = (date: Date, unit: TickUnit) => {
		const jd = dateToJD(date);
		if (jd >= startJd && jd <= endJd) ticks.push({ jd, date, unit });
	};

	// Pick the unit off the spacing the ticks would want, not off the span: at
	// six ticks a 150-day run wants a 25-day step, which is a month rather than
	// a clumsy multiple of a day.
	const stepDays = spanDays / maxTicks;
	if (stepDays > MAX_MONTHS_PER_TICK * DAYS_PER_MONTH) {
		const step = stepFor(YEAR_STEPS, spanDays / DAYS_PER_YEAR, maxTicks);
		// Round in the calendar's own numbering: 2570 BE and 100 BC, not 2030
		// CE and 101 BC. The Japanese has no numbering to round across eras.
		for (const year of roundYears(start.getFullYear(), end.getFullYear(), step, eraStart ?? null)) {
			const date = atYear(year);
			// An invalid date compares false, so this also stops at the end of the range.
			if (!(date <= end)) break;
			push(date, 'year');
		}
	} else if (stepDays >= 25) {
		const step = stepFor(MONTH_STEPS, spanDays / DAYS_PER_MONTH, maxTicks);
		// Count months from year zero so alignment doesn't restart each year.
		const startIndex = start.getFullYear() * 12 + start.getMonth();
		for (let index = Math.ceil(startIndex / step) * step; ; index += step) {
			const date = atMonth(Math.floor(index / 12), index % 12);
			if (!(date <= end)) break;
			push(date, 'month');
		}
	} else if (stepDays >= 0.5) {
		const step = stepFor(DAY_STEPS, spanDays, maxTicks);
		const date = new Date(start);
		date.setHours(0, 0, 0, 0);
		if (date < start) date.setDate(date.getDate() + 1);
		for (; date <= end; date.setDate(date.getDate() + step)) push(new Date(date), 'day');
	} else if (decimalTime) {
		const step = stepFor(DECIMAL_HOUR_STEPS, spanDays * DECIMAL_HOURS_PER_DAY, maxTicks);
		const midnight = new Date(start);
		midnight.setHours(0, 0, 0, 0);
		// Decimal hours run off local midnight in fixed lengths: a day that
		// changes its clocks is still ten of them, of its own length each.
		for (let day = 0; day <= Math.ceil(spanDays) + 1; day++) {
			const dayStart = new Date(midnight);
			dayStart.setDate(dayStart.getDate() + day);
			const dayEnd = new Date(dayStart);
			dayEnd.setDate(dayEnd.getDate() + 1);
			const length = dayEnd.getTime() - dayStart.getTime();
			for (let hour = 0; hour < DECIMAL_HOURS_PER_DAY; hour += step) {
				const date = new Date(dayStart.getTime() + (length * hour) / DECIMAL_HOURS_PER_DAY);
				if (date > end) break;
				if (date >= start) push(date, 'hour');
			}
			if (dayEnd > end) break;
		}
	} else {
		const step = stepFor(HOUR_STEPS, spanDays * HOURS_PER_DAY, maxTicks);
		const date = new Date(start);
		date.setMinutes(0, 0, 0);
		while (date < start || date.getHours() % step !== 0) date.setHours(date.getHours() + 1);
		for (; date <= end; date.setHours(date.getHours() + step)) push(new Date(date), 'hour');
	}

	return ticks;
}

/**
 * Ticks for a calendar whose months are not the Gregorian's, on the month and
 * year starts its own fields give (see {@link CalendarScanner}).
 */
function calendarTicks(
	startJd: number,
	endJd: number,
	maxTicks: number,
	calendar: CalendarId,
	decimalTime: boolean
): AxisTick[] {
	const spanDays = endJd - startJd;
	const stepDays = spanDays / maxTicks;
	// Days and hours fall where they do in any calendar; only their labels change.
	if (stepDays < 25) return axisTicks(startJd, endJd, maxTicks, 'gregory', decimalTime);

	const scan = scannerFor(calendar);
	const ticks: AxisTick[] = [];
	const push = (jdn: number, unit: TickUnit) => {
		const date = jdnToLocalMidnight(jdn);
		const jd = dateToJD(date);
		if (jd >= startJd && jd <= endJd) ticks.push({ jd, date, unit });
	};
	const firstJdn = dateToJdn(jdToDate(startJd));
	const lastJdn = dateToJdn(jdToDate(Math.min(endJd, LAST_DATE_JD)));

	if (stepDays > MAX_MONTHS_PER_TICK * DAYS_PER_MONTH) {
		const step = stepFor(YEAR_STEPS, spanDays / DAYS_PER_YEAR, maxTicks);
		let year = Math.ceil(scan.fields(firstJdn).year / step) * step;
		for (let n = 0; n <= maxTicks * 2; n++, year += step) {
			const jdn = scan.startOfYear(year, firstJdn);
			if (jdn > lastJdn) break;
			if (jdn >= firstJdn) push(jdn, 'year');
		}
	} else {
		const step = stepFor(MONTH_STEPS, spanDays / DAYS_PER_MONTH, maxTicks);
		let jdn = scan.yearStart(firstJdn);
		// The month's place in its year, so steps of three land on the quarters.
		let index = 0;
		while (jdn <= lastJdn) {
			if (jdn >= firstJdn && index % step === 0) push(jdn, 'month');
			const next = scan.nextMonthStart(jdn);
			if (!(next > jdn)) break;
			index = scan.fields(next).yearKey === scan.fields(jdn).yearKey ? index + 1 : 0;
			jdn = next;
		}
	}
	return ticks;
}

/**
 * The Gregorian years from `first` to `last` whose number, as the calendar
 * writes it, is a multiple of `step`. `eraStart` is the year the count reaches
 * 1 in (see {@link GREGORIAN_STRUCTURED}); the years before it count back
 * down, so rounding there runs the other way. Null rounds the Gregorian year.
 */
function roundYears(first: number, last: number, step: number, eraStart: number | null): number[] {
	if (eraStart === null) {
		const out: number[] = [];
		for (let year = Math.ceil(first / step) * step; year <= last; year += step) out.push(year);
		return out;
	}
	const out: number[] = [];
	// Before the era: the year written n is eraStart − n, counting down.
	const before = Math.min(last, eraStart - 1);
	if (first <= before) {
		for (let n = Math.floor((eraStart - first) / step) * step; n >= 1; n -= step) {
			const year = eraStart - n;
			if (year > before) break;
			out.push(year);
		}
	}
	// From the era on: the year written n is eraStart + n − 1.
	const from = Math.max(first, eraStart);
	for (let n = Math.ceil((from - eraStart + 1) / step) * step; ; n += step) {
		const year = eraStart + n - 1;
		if (year > last) break;
		out.push(year);
	}
	return out;
}
