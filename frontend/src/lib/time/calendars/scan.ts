/**
 * Where a calendar's months and years begin, found by reading its fields.
 *
 * Nothing about a calendar's structure is assumed beyond months of at least
 * five days (the Coptic and Republican complementary days) and years of a
 * dozen or so months, so this works for any calendar {@link calendarFields}
 * reads: Intl's, leap months and all, and the two kept here. The timeline's
 * ticks and the date picker both stand on it.
 */

import { calendarFields, type CalendarFields, type CalendarId } from './index';

/** How far past day 29 a month-start search walks before giving up. */
const MONTH_SEARCH_DAYS = 4;
/** More months than any calendar's year has. */
export const MAX_MONTHS_PER_YEAR = 14;
/** 1 January 2000: where year guesses are measured from. */
const ANCHOR_JDN = 2_451_545;
/** Mean years, in days: the tabular Hijri, and the Gregorian. */
const LUNAR_YEAR = 354.36667;
const SOLAR_YEAR = 365.2425;
/** Fields remembered per calendar before the memo starts over. */
const MEMO_LIMIT = 50_000;

export interface YearTable {
	year: number;
	/** JDN of each month's first day, in order. */
	monthStarts: number[];
	/** JDN of the next year's first day. */
	end: number;
}

export class CalendarScanner {
	readonly calendar: CalendarId;
	#memo = new Map<number, CalendarFields>();
	#years = new Map<number, YearTable>();
	#meanYear: number | undefined;

	constructor(calendar: CalendarId) {
		this.calendar = calendar;
	}

	fields(jdn: number): CalendarFields {
		let f = this.#memo.get(jdn);
		if (!f) {
			if (this.#memo.size > MEMO_LIMIT) this.#memo.clear();
			this.#memo.set(jdn, (f = calendarFields(this.calendar, jdn)));
		}
		return f;
	}

	monthStart(jdn: number): number {
		return jdn - (this.fields(jdn).day - 1);
	}

	/** The first day of the month after the one `start` begins. */
	nextMonthStart(start: number): number {
		const here = this.fields(start);
		let jdn = start + 29;
		for (let i = 0; i < MONTH_SEARCH_DAYS; i++, jdn++) {
			const f = this.fields(jdn);
			if (f.monthKey !== here.monthKey || f.yearKey !== here.yearKey) {
				// Past a short month and into the next: step back to its first day.
				return jdn - (f.day - 1);
			}
		}
		return jdn;
	}

	/** The first day of the year `jdn` is in. */
	yearStart(jdn: number): number {
		let start = this.monthStart(jdn);
		for (let i = 0; i < MAX_MONTHS_PER_YEAR; i++) {
			const before = this.monthStart(start - 1);
			if (this.fields(before).yearKey !== this.fields(start).yearKey) break;
			start = before;
		}
		return start;
	}

	/**
	 * The calendar's mean year: the lunar 354.367 days for a Hijri calendar,
	 * the solar year for every other, the lunisolar ones included. Which one is
	 * read off twenty years of the calendar; the length itself is the known
	 * one, since twenty lunisolar years can run a fortnight off their mean and
	 * a guess built on that drifts a year in a few centuries.
	 */
	meanYear(): number {
		if (this.#meanYear === undefined) {
			const anchor = this.yearStart(ANCHOR_JDN);
			const probe = this.yearStart(anchor + 20 * 365);
			const years = this.fields(probe).year - this.fields(anchor).year;
			this.#meanYear = years > 0 && (probe - anchor) / years < 360 ? LUNAR_YEAR : SOLAR_YEAR;
		}
		return this.#meanYear;
	}

	/** A day inside the year numbered `year`, found without laying out any year
	 *  but this calendar's first: half a mean year past where the year should
	 *  start is well inside it either way. Cheap enough for a list of a
	 *  thousand year names. */
	dayInYear(year: number, near = ANCHOR_JDN): number {
		const anchor = this.yearStart(near);
		return Math.round(anchor + (year - this.fields(anchor).year + 0.5) * this.meanYear());
	}

	/** The first day of the year numbered `year`: a guess off the mean year,
	 *  corrected by however many years it lands off. */
	startOfYear(year: number, near = ANCHOR_JDN): number {
		const mean = this.meanYear();
		let guess = this.dayInYear(year, near);
		let jdn = this.yearStart(guess);
		for (let i = 0; i < 8; i++) {
			const found = this.fields(jdn).year;
			if (found === year || !Number.isFinite(found)) break;
			guess += Math.round((year - found) * mean);
			jdn = this.yearStart(guess);
		}
		return jdn;
	}

	/** The months of the year numbered `year`. */
	year(year: number): YearTable {
		let table = this.#years.get(year);
		if (!table) {
			const start = this.startOfYear(year);
			const key = this.fields(start).yearKey;
			const monthStarts = [start];
			let next = this.nextMonthStart(start);
			while (this.fields(next).yearKey === key && monthStarts.length < MAX_MONTHS_PER_YEAR) {
				monthStarts.push(next);
				next = this.nextMonthStart(next);
			}
			table = { year, monthStarts, end: next };
			this.#years.set(year, table);
		}
		return table;
	}
}

const scanners = new Map<CalendarId, CalendarScanner>();

/** One scanner per calendar, so what one finds the next reuses. */
export function scannerFor(calendar: CalendarId): CalendarScanner {
	let scanner = scanners.get(calendar);
	if (!scanner) scanners.set(calendar, (scanner = new CalendarScanner(calendar)));
	return scanner;
}
