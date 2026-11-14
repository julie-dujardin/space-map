/**
 * The calendars a date can be shown in: Intl's, plus the Julian and the French
 * Republican, which Intl lacks. Every worded date goes through
 * {@link calendarDateFormat} so one choice holds everywhere; ISO 8601 stays
 * Gregorian.
 */

import { dateToJdn, jdnToJulian, jdnToUtcNoon, julianToJdn } from './day-number';
import { formatRepublican, jdnToRepublican } from './republican';

/** A calendar Intl names (`gregory`, `hebrew`, `islamic-umalqura`, …), or one
 *  of the two kept here. */
export type CalendarId = string;

export const JULIAN = 'julian';
export const FRENCH_REPUBLICAN = 'french-republican';

/**
 * The calendars in civil or religious use that settings offer. Left out:
 * `iso8601` (the Gregorian again), `islamic` and `islamic-rgsa` (ICU fakes
 * sighting with arithmetic), `islamic-tbla` and `ethioaa` (scholarly).
 */
const OFFERED_INTL = [
	'gregory',
	'buddhist',
	'chinese',
	'coptic',
	'dangi',
	'ethiopic',
	'hebrew',
	'indian',
	'islamic-civil',
	'islamic-umalqura',
	'japanese',
	'persian',
	'roc'
] as const;

/**
 * Calendars with the Gregorian's months and days, so they share its
 * boundaries. Each maps to the astronomical year its count reaches 1 in; years
 * before it count back down with no year 0. The Japanese restarts each era.
 */
export const GREGORIAN_STRUCTURED: ReadonlyMap<CalendarId, number | null> = new Map([
	['gregory', 1],
	['iso8601', 1],
	['buddhist', -542],
	['roc', 1912],
	['japanese', null]
]);

// Asked per frame through the settings' resolved calendar, so answered once.
const supported = new Map<string, boolean>();

function intlSupports(calendar: string): boolean {
	let answer = supported.get(calendar);
	if (answer === undefined) {
		try {
			answer = Intl.supportedValuesOf('calendar').includes(calendar);
		} catch {
			// No `supportedValuesOf`: ask a formatter whether it kept the calendar.
			try {
				answer =
					new Intl.DateTimeFormat(`en-u-ca-${calendar}`).resolvedOptions().calendar === calendar;
			} catch {
				answer = false;
			}
		}
		supported.set(calendar, answer);
	}
	return answer;
}

export function isKnownCalendar(calendar: string): boolean {
	return calendar === JULIAN || calendar === FRENCH_REPUBLICAN || intlSupports(calendar);
}

/** The calendars the settings list, the ones this browser can draw. */
export function offeredCalendars(): CalendarId[] {
	return [...OFFERED_INTL.filter(intlSupports), JULIAN, FRENCH_REPUBLICAN];
}

/**
 * The calendar the browser's own locale uses. "Auto" follows this rather than
 * the page's language: a browser in fa-IR wants the Persian calendar even on a
 * page we only have in English.
 */
let ownCalendar: CalendarId | undefined;
export function browserCalendar(): CalendarId {
	if (ownCalendar === undefined) {
		try {
			const calendar = new Intl.DateTimeFormat().resolvedOptions().calendar;
			ownCalendar = calendar === 'iso8601' || !calendar ? 'gregory' : calendar;
		} catch {
			ownCalendar = 'gregory';
		}
	}
	return ownCalendar;
}

/** `locale` asking Intl for `calendar`, where Intl has it; the two kept here
 *  leave the locale as it is. */
export function localeWithCalendar(locale: string, calendar: CalendarId): string {
	if (calendar === JULIAN || calendar === FRENCH_REPUBLICAN) return locale;
	try {
		return new Intl.Locale(locale, { calendar }).toString();
	} catch {
		return `${locale}-u-ca-${calendar}`;
	}
}

/** Formats dates in one locale and calendar; the subset of
 *  `Intl.DateTimeFormat` the app uses. */
export interface CalendarDateFormat {
	format(date: Date): string;
	/** A span, collapsed to one date where the fields asked for agree. */
	formatRange(start: Date, end: Date): string;
}

const DATE_FIELDS = ['weekday', 'era', 'year', 'month', 'day'] as const;
const TIME_FIELDS = [
	'hour',
	'minute',
	'second',
	'fractionalSecondDigits',
	'dayPeriod',
	'hour12',
	'hourCycle',
	'timeZoneName'
] as const;

function pick(
	opts: Intl.DateTimeFormatOptions,
	keys: readonly (keyof Intl.DateTimeFormatOptions)[]
): Intl.DateTimeFormatOptions {
	const out: Record<string, unknown> = {};
	for (const key of keys) if (opts[key] !== undefined) out[key] = opts[key];
	return out as Intl.DateTimeFormatOptions;
}

function hasAny(opts: Intl.DateTimeFormatOptions, keys: readonly string[]): boolean {
	return keys.some((key) => opts[key as keyof Intl.DateTimeFormatOptions] !== undefined);
}

function joinRange(a: string, b: string): string {
	return a === b ? a : `${a} – ${b}`;
}

class IntlCalendarFormat implements CalendarDateFormat {
	#format: Intl.DateTimeFormat;
	constructor(locale: string, calendar: CalendarId, opts: Intl.DateTimeFormatOptions) {
		this.#format = new Intl.DateTimeFormat(localeWithCalendar(locale, calendar), opts);
	}
	format(date: Date): string {
		return this.#format.format(date);
	}
	formatRange(start: Date, end: Date): string {
		if (typeof this.#format.formatRange === 'function') return this.#format.formatRange(start, end);
		return joinRange(this.format(start), this.format(end));
	}
}

/** Part types that name the date rather than the time of day. The weekday is
 *  not among them: the same day is the same day of the week in both. */
const SWAPPED_PARTS = new Set<string>(['era', 'year', 'relatedYear', 'month', 'day']);

/** Intl has no Julian calendar, but it shares the Gregorian's months, so the
 *  locale's Gregorian pattern is reused with the Julian date's parts. */
class JulianFormat implements CalendarDateFormat {
	#real: Intl.DateTimeFormat;
	#dateOnly: Intl.DateTimeFormat;
	#timeZone: string | undefined;
	constructor(locale: string, opts: Intl.DateTimeFormatOptions) {
		const gregorian = localeWithCalendar(locale, 'gregory');
		this.#real = new Intl.DateTimeFormat(gregorian, opts);
		this.#dateOnly = new Intl.DateTimeFormat(gregorian, {
			...pick(opts, DATE_FIELDS),
			timeZone: 'UTC'
		});
		this.#timeZone = opts.timeZone;
	}
	format(date: Date): string {
		const { year, month, day } = jdnToJulian(dateToJdn(date, this.#timeZone));
		// Noon first, so a day at the very edge of `Date`'s range is still one.
		const shown = new Date(0);
		shown.setUTCHours(12);
		shown.setUTCFullYear(year, month - 1, day);
		// Past `Date`'s range there is no Julian day to show.
		if (Number.isNaN(shown.getTime())) return this.#real.format(date);
		const swapped = new Map(
			this.#dateOnly.formatToParts(shown).map((part) => [part.type, part.value] as const)
		);
		return this.#real
			.formatToParts(date)
			.map((part) =>
				SWAPPED_PARTS.has(part.type) ? (swapped.get(part.type) ?? part.value) : part.value
			)
			.join('');
	}
	formatRange(start: Date, end: Date): string {
		return joinRange(this.format(start), this.format(end));
	}
}

/**
 * The Republic's decimal time: ten hours from midnight, each of a hundred
 * minutes of a hundred seconds. Taken as a share of the local day, so a day
 * whose clocks change still has ten hours.
 */
export function formatDecimalTime(
	date: Date,
	{ seconds = false, timeZone }: { seconds?: boolean; timeZone?: string } = {}
): string {
	const start = new Date(date);
	const end = new Date(date);
	if (timeZone === 'UTC') {
		start.setUTCHours(0, 0, 0, 0);
		end.setUTCHours(24, 0, 0, 0);
	} else {
		start.setHours(0, 0, 0, 0);
		end.setTime(start.getTime());
		end.setDate(end.getDate() + 1);
	}
	const fraction = (date.getTime() - start.getTime()) / (end.getTime() - start.getTime());
	const units = Math.min(99_999, Math.floor(fraction * 100_000));
	const pad = (n: number) => String(n).padStart(2, '0');
	const hm = `${Math.floor(units / 10_000)}:${pad(Math.floor(units / 100) % 100)}`;
	return seconds ? `${hm}:${pad(units % 100)}` : hm;
}

export interface CalendarFormatExtras {
	/** Write the time of day in the Republic's decimal hours. Only the
	 *  Republican calendar takes it. */
	decimalTime?: boolean;
}

class RepublicanFormat implements CalendarDateFormat {
	#locale: string;
	#opts: Intl.DateTimeFormatOptions;
	#time: { format(date: Date): string } | null;
	#hasDate: boolean;
	constructor(locale: string, opts: Intl.DateTimeFormatOptions, decimalTime: boolean) {
		this.#locale = locale;
		this.#opts = opts;
		const hasTime = hasAny(opts, TIME_FIELDS);
		// Intl's own default when no field is named: the date, in full.
		this.#hasDate = hasAny(opts, DATE_FIELDS) || !hasTime;
		const decimal = {
			format: (date: Date) =>
				formatDecimalTime(date, { seconds: opts.second !== undefined, timeZone: opts.timeZone })
		};
		this.#time = !hasTime
			? null
			: decimalTime
				? decimal
				: new Intl.DateTimeFormat(locale, { ...pick(opts, TIME_FIELDS), timeZone: opts.timeZone });
	}
	format(date: Date): string {
		const out: string[] = [];
		if (this.#hasDate) {
			const opts = this.#opts;
			const named = hasAny(opts, DATE_FIELDS);
			out.push(
				formatRepublican(jdnToRepublican(dateToJdn(date, opts.timeZone)), this.#locale, {
					year: !named || opts.year !== undefined,
					month: !named || opts.month !== undefined,
					day: !named || opts.day !== undefined,
					weekday: opts.weekday !== undefined
				})
			);
		}
		if (this.#time) out.push(this.#time.format(date));
		return out.join(' ');
	}
	formatRange(start: Date, end: Date): string {
		return joinRange(this.format(start), this.format(end));
	}
}

/** A formatter for `opts` in a locale and calendar. Uncached, like an
 *  `Intl.DateTimeFormat`. */
export function calendarDateFormat(
	locale: string,
	calendar: CalendarId,
	opts: Intl.DateTimeFormatOptions,
	{ decimalTime = false }: CalendarFormatExtras = {}
): CalendarDateFormat {
	if (calendar === JULIAN) return new JulianFormat(locale, opts);
	if (calendar === FRENCH_REPUBLICAN) return new RepublicanFormat(locale, opts, decimalTime);
	return new IntlCalendarFormat(locale, calendar, opts);
}

/** A calendar's name in the reader's language. Intl knows its own; the two
 *  kept here bring theirs. */
export function calendarName(
	calendar: CalendarId,
	locale: string,
	own: { julian: () => string; republican: () => string }
): string {
	if (calendar === JULIAN) return own.julian();
	if (calendar === FRENCH_REPUBLICAN) return own.republican();
	try {
		return new Intl.DisplayNames(locale, { type: 'calendar' }).of(calendar) ?? calendar;
	} catch {
		return calendar;
	}
}

// ---------------------------------------------------------------------------
// Fields, for finding where months and years begin

export interface CalendarFields {
	/** The year's number as the calendar writes it, for aligning ticks on
	 *  round years. Era-relative where the calendar has eras. */
	year: number;
	/** Changes exactly when the year does, era included. */
	yearKey: string;
	/** Changes exactly when the month does, within a year. A leap month has
	 *  its own (Hebrew Adar I, Chinese 6bis). */
	monthKey: string;
	day: number;
}

const fieldFormats = new Map<CalendarId, Intl.DateTimeFormat>();

/**
 * First days of the Coptic and Ethiopic eras. These two are counted here
 * because Intl numbers the years before their epochs backwards, in an era it
 * does not always name.
 */
const ALEXANDRIAN_EPOCHS: ReadonlyMap<CalendarId, number> = new Map([
	['coptic', julianToJdn(284, 8, 29)],
	['ethiopic', julianToJdn(8, 8, 29)]
]);

function alexandrianFields(epoch: number, jdn: number): CalendarFields {
	const year = Math.floor((4 * (jdn - epoch) + 1463) / 1461);
	const dayOfYear = jdn - (epoch + 365 * (year - 1) + Math.floor(year / 4));
	return {
		year,
		yearKey: String(year),
		monthKey: String(Math.floor(dayOfYear / 30) + 1),
		day: (dayOfYear % 30) + 1
	};
}

/** The calendar's year, month and day for the day `jdn`. */
export function calendarFields(calendar: CalendarId, jdn: number): CalendarFields {
	const epoch = ALEXANDRIAN_EPOCHS.get(calendar);
	if (epoch !== undefined) return alexandrianFields(epoch, jdn);
	if (calendar === JULIAN) {
		const { year, month, day } = jdnToJulian(jdn);
		return { year, yearKey: String(year), monthKey: String(month), day };
	}
	if (calendar === FRENCH_REPUBLICAN) {
		const { year, month, day } = jdnToRepublican(jdn);
		return { year, yearKey: String(year), monthKey: String(month), day };
	}
	let format = fieldFormats.get(calendar);
	if (!format) {
		format = new Intl.DateTimeFormat(localeWithCalendar('en', calendar), {
			era: 'short',
			year: 'numeric',
			month: 'numeric',
			day: 'numeric',
			timeZone: 'UTC',
			numberingSystem: 'latn'
		});
		fieldFormats.set(calendar, format);
	}
	let era = '';
	let year = '';
	let month = '';
	let day = '';
	for (const part of format.formatToParts(jdnToUtcNoon(jdn))) {
		if (part.type === 'era') era = part.value;
		// The Chinese and Dangi count by a related Gregorian year, which TS's lib omits.
		else if (part.type === 'year' || (part.type as string) === 'relatedYear') year = part.value;
		else if (part.type === 'month') month = part.value;
		else if (part.type === 'day') day = part.value;
	}
	return { year: Number(year), yearKey: `${era} ${year}`, monthKey: month, day: Number(day) };
}
