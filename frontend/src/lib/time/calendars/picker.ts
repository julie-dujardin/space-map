/**
 * The reader's calendar as the date picker needs it: an
 * `@internationalized/date` Calendar, so bits-ui lays out that calendar's
 * months rather than the Gregorian's.
 *
 * The library brings arithmetic for some calendars of its own, but not the
 * Chinese, Julian or Republican, and its tables need not agree with the
 * browser's to the day. So every calendar whose months are not the
 * Gregorian's is laid out from the same fields the rest of the app formats
 * with (see {@link CalendarScanner}): the picker cannot show a month that the
 * time bar would then name differently. Calendars with the Gregorian's months
 * (Buddhist, Japanese, Minguo) keep the Gregorian grid and only rename it.
 */

import {
	CalendarDate,
	GregorianCalendar,
	toCalendar,
	type AnyCalendarDate,
	type Calendar,
	type CalendarIdentifier,
	type DateValue
} from '@internationalized/date';
import {
	GREGORIAN_STRUCTURED,
	calendarDateFormat,
	type CalendarDateFormat,
	type CalendarId
} from './index';
import { jdnToUtcNoon } from './day-number';
import { scannerFor, type CalendarScanner, type YearTable } from './scan';

const BEFORE = 'before';
const AFTER = 'after';
/** Room enough either side of the epoch for any date the map reaches. */
const YEARS_PER_ERA = 1_000_000;

/** A calendar laid out from its own fields. Years count up through `after`
 *  and back through `before` from the epoch, so the library's positive years
 *  hold Republican dates before 1792. */
class ScannedCalendar implements Calendar {
	readonly identifier: CalendarIdentifier;
	readonly #scan: CalendarScanner;

	constructor(calendar: CalendarId) {
		// Not one of the library's identifiers for the two kept here; nothing
		// looks a calendar up by it.
		this.identifier = calendar as CalendarIdentifier;
		this.#scan = scannerFor(calendar);
	}

	#table(date: AnyCalendarDate): YearTable {
		return this.#scan.year(date.era === BEFORE ? 1 - date.year : date.year);
	}

	#monthIndex(date: AnyCalendarDate, table: YearTable): number {
		return Math.min(Math.max(date.month, 1), table.monthStarts.length) - 1;
	}

	fromJulianDay(jd: number): CalendarDate {
		const jdn = Math.round(jd);
		let year = this.#scan.fields(jdn).year;
		let table = this.#scan.year(year);
		// An era change can number a year oddly; the neighbours own the day then.
		if (jdn < table.monthStarts[0] || jdn >= table.end) {
			for (const near of [year - 1, year + 1]) {
				const t = this.#scan.year(near);
				if (jdn >= t.monthStarts[0] && jdn < t.end) {
					table = t;
					year = near;
					break;
				}
			}
		}
		let month = 1;
		table.monthStarts.forEach((start, i) => {
			if (start <= jdn) month = i + 1;
		});
		const day = jdn - table.monthStarts[month - 1] + 1;
		return year > 0
			? new CalendarDate(this, AFTER, year, month, day)
			: new CalendarDate(this, BEFORE, 1 - year, month, day);
	}

	toJulianDay(date: AnyCalendarDate): number {
		const table = this.#table(date);
		return table.monthStarts[this.#monthIndex(date, table)] + date.day - 1;
	}

	getDaysInMonth(date: AnyCalendarDate): number {
		const table = this.#table(date);
		const i = this.#monthIndex(date, table);
		return (table.monthStarts[i + 1] ?? table.end) - table.monthStarts[i];
	}

	getMonthsInYear(date: AnyCalendarDate): number {
		return this.#table(date).monthStarts.length;
	}

	getYearsInEra(): number {
		return YEARS_PER_ERA;
	}

	getEras(): string[] {
		return [BEFORE, AFTER];
	}

	getMaximumMonthsInYear(): number {
		return 13;
	}

	getMaximumDaysInMonth(): number {
		return 31;
	}

	isInverseEra(date: AnyCalendarDate): boolean {
		return date.era === BEFORE;
	}

	/** Year 0 is year 1 of the other era. */
	balanceDate(date: AnyCalendarDate): void {
		if (date.year > 0) return;
		const mutable = date as { era: string; year: number };
		mutable.era = date.era === BEFORE ? AFTER : BEFORE;
		mutable.year = 1 - date.year;
	}

	isEqual(other: Calendar): boolean {
		return other.identifier === this.identifier;
	}
}

const GREGORIAN = new GregorianCalendar();
const pickerCalendars = new Map<CalendarId, Calendar>();

/** The calendar the picker lays its months out in. */
export function pickerCalendar(calendar: CalendarId): Calendar {
	if (GREGORIAN_STRUCTURED.has(calendar)) return GREGORIAN;
	let found = pickerCalendars.get(calendar);
	if (!found) pickerCalendars.set(calendar, (found = new ScannedCalendar(calendar)));
	return found;
}

/** A proleptic Gregorian day (astronomical year) in the picker's calendar. */
export function toPickerDate(
	year: number,
	month: number,
	day: number,
	calendar: CalendarId
): CalendarDate {
	const gregorian =
		year > 0
			? new CalendarDate(GREGORIAN, 'AD', year, month, day)
			: new CalendarDate(GREGORIAN, 'BC', 1 - year, month, day);
	return toCalendar(gregorian, pickerCalendar(calendar));
}

/** A picked day back as a proleptic Gregorian date (astronomical year). */
export function fromPickerDate(value: DateValue): { year: number; month: number; day: number } {
	const g = toCalendar(value, GREGORIAN);
	return { year: g.era === 'BC' ? 1 - g.year : g.year, month: g.month, day: g.day };
}

/** The year as one number counting through the epoch: 0 and below before it. */
export function extendedYear(date: AnyCalendarDate): number {
	return date.calendar.isInverseEra?.(date) ? 1 - date.year : date.year;
}

/** `date` moved into the year `year` counts as {@link extendedYear}. */
export function withExtendedYear<T extends DateValue>(date: T, year: number): T {
	const eras = date.calendar.getEras();
	return (
		year > 0
			? date.set({ era: eras[eras.length - 1], year })
			: date.set({ era: eras[0], year: 1 - year })
	) as T;
}

/** The day a picker date stands for, at UTC noon, for formatting it. */
export function pickerDateToUtcNoon(date: AnyCalendarDate): Date {
	return jdnToUtcNoon(date.calendar.toJulianDay(date));
}

const yearFormats = new Map<string, CalendarDateFormat>();

/**
 * A year's name for the year list, without laying the year out: a list of a
 * thousand years cannot afford to find each one's months, nor a formatter each.
 */
export function yearLabel(calendar: CalendarId, locale: string, year: number): string {
	const key = `${calendar}|${locale}`;
	let format = yearFormats.get(key);
	if (!format) {
		format = calendarDateFormat(locale, calendar, { year: 'numeric', timeZone: 'UTC' });
		yearFormats.set(key, format);
	}
	if (GREGORIAN_STRUCTURED.has(calendar)) {
		const mid = new Date(Date.UTC(2000, 6, 1, 12));
		mid.setUTCFullYear(year);
		return format.format(mid);
	}
	return format.format(jdnToUtcNoon(scannerFor(calendar).dayInYear(year)));
}
