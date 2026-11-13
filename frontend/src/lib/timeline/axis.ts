/**
 * The pieces every timeline needs, whatever it is a timeline of.
 *
 * A trip is legs; a spacecraft's record is what it did. Both are a run of
 * spans on the same clock, drawn as one strip — so where the clock stands in
 * them, and what dates to label the axis with, live here rather than with
 * either subject.
 */

import { dateToJD, jdToDate, LAST_DATE_JD } from '$lib/time/jd';
import { calendarFields, GREGORIAN_STRUCTURED, type CalendarId } from '$lib/time/calendars';
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
 * formatted against. The boundaries are the reader's calendar's: a Hijri
 * year starts where it does, not on 1 January.
 */
export function axisTicks(
	startJd: number,
	endJd: number,
	maxTicks = 6,
	calendar: CalendarId = 'gregory'
): AxisTick[] {
	const spanDays = endJd - startJd;
	if (!(spanDays > 0) || !Number.isFinite(spanDays) || maxTicks < 1) return [];
	const yearOffset = GREGORIAN_STRUCTURED.get(calendar);
	if (yearOffset === undefined) return calendarTicks(startJd, endJd, maxTicks, calendar);

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
	if (stepDays >= DAYS_PER_MONTH * 11) {
		const step = stepFor(YEAR_STEPS, spanDays / DAYS_PER_YEAR, maxTicks);
		// Round in the calendar's own numbering: 2570 BE, not 2030 CE.
		const offset = yearOffset ?? 0;
		const first = Math.ceil((start.getFullYear() + offset) / step) * step - offset;
		for (let year = first; ; year += step) {
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
	} else {
		const step = stepFor(HOUR_STEPS, spanDays * HOURS_PER_DAY, maxTicks);
		const date = new Date(start);
		date.setMinutes(0, 0, 0);
		while (date < start || date.getHours() % step !== 0) date.setHours(date.getHours() + 1);
		for (; date <= end; date.setHours(date.getHours() + step)) push(new Date(date), 'hour');
	}

	return ticks;
}

/** The longest a month runs past 29 days, plus slack: how far the month-start
 *  search may walk before giving up on a calendar that misbehaves. */
const MONTH_SEARCH_DAYS = 4;
/** More months than any calendar's year has. */
const MAX_MONTHS_PER_YEAR = 14;

/**
 * Ticks for a calendar whose months are not the Gregorian's. Nothing about
 * its structure is assumed beyond months of at least five days (the Coptic
 * and Republican complementary days) and years of a dozen or so months: month
 * and year starts are found by reading the calendar's own fields, so any
 * calendar Intl draws ticks right, leap months and all.
 */
function calendarTicks(
	startJd: number,
	endJd: number,
	maxTicks: number,
	calendar: CalendarId
): AxisTick[] {
	const spanDays = endJd - startJd;
	const ticks: AxisTick[] = [];
	const memo = new Map<number, ReturnType<typeof calendarFields>>();
	const fields = (jdn: number) => {
		let f = memo.get(jdn);
		if (!f) memo.set(jdn, (f = calendarFields(calendar, jdn)));
		return f;
	};
	const monthStart = (jdn: number) => jdn - (fields(jdn).day - 1);
	/** The first day of the month after the one `start` begins. */
	const nextMonthStart = (start: number) => {
		const here = fields(start);
		let jdn = start + 29;
		for (let i = 0; i < MONTH_SEARCH_DAYS; i++, jdn++) {
			const f = fields(jdn);
			if (f.monthKey !== here.monthKey || f.yearKey !== here.yearKey) {
				// Past a short month and into the next: step back to its first day.
				return jdn - (f.day - 1);
			}
		}
		return jdn;
	};
	const yearStart = (jdn: number) => {
		let start = monthStart(jdn);
		for (let i = 0; i < MAX_MONTHS_PER_YEAR; i++) {
			const before = monthStart(start - 1);
			if (fields(before).yearKey !== fields(start).yearKey) break;
			start = before;
		}
		return start;
	};
	const push = (jdn: number, unit: TickUnit) => {
		const date = jdnToLocalMidnight(jdn);
		const jd = dateToJD(date);
		if (jd >= startJd && jd <= endJd) ticks.push({ jd, date, unit });
	};

	const firstJdn = dateToJdn(jdToDate(startJd));
	const lastJdn = dateToJdn(jdToDate(Math.min(endJd, LAST_DATE_JD)));
	const stepDays = spanDays / maxTicks;

	if (stepDays >= DAYS_PER_MONTH * 11) {
		const step = stepFor(YEAR_STEPS, spanDays / DAYS_PER_YEAR, maxTicks);
		const anchor = yearStart(firstJdn);
		const anchorYear = fields(anchor).year;
		const meanYear = meanYearDays(anchor, anchorYear, yearStart, fields);
		// Each tick's year is found from a guess at its start, then snapped onto
		// it: a guess millennia out may land a year off.
		let year = Math.ceil(anchorYear / step) * step;
		for (let n = 0; n <= maxTicks * 2; n++, year += step) {
			let jdn = yearStart(Math.round(anchor + (year - anchorYear + 0.5) * meanYear));
			for (let i = 0; i < 3 && fields(jdn).year !== year; i++) {
				jdn =
					fields(jdn).year < year
						? yearStart(jdn + Math.round(meanYear * 1.5))
						: yearStart(jdn - 1);
			}
			if (jdn > lastJdn) break;
			if (jdn >= firstJdn) push(jdn, 'year');
		}
	} else if (stepDays >= 25) {
		const step = stepFor(MONTH_STEPS, spanDays / DAYS_PER_MONTH, maxTicks);
		let jdn = yearStart(firstJdn);
		// The month's place in its year, so steps of three land on the quarters.
		let index = 0;
		while (jdn <= lastJdn) {
			if (jdn >= firstJdn && index % step === 0) push(jdn, 'month');
			const next = nextMonthStart(jdn);
			if (!(next > jdn)) break;
			index = fields(next).yearKey === fields(jdn).yearKey ? index + 1 : 0;
			jdn = next;
		}
	} else {
		// Days and hours fall where they do in any calendar; only their labels change.
		return axisTicks(startJd, endJd, maxTicks, 'gregory');
	}
	return ticks;
}

/** The calendar's mean year, measured over twenty of them from `anchor`:
 *  354 days for a lunar calendar, about 365 for the rest. A calendar whose
 *  year count jumps there (an era change) gets the solar year. */
function meanYearDays(
	anchor: number,
	anchorYear: number,
	yearStart: (jdn: number) => number,
	fields: (jdn: number) => { year: number }
): number {
	const probe = yearStart(anchor + 20 * 365);
	const years = fields(probe).year - anchorYear;
	const mean = (probe - anchor) / years;
	return years >= 15 && years <= 25 && mean > 300 && mean < 400 ? mean : DAYS_PER_YEAR;
}
