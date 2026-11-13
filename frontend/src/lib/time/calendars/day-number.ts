/**
 * Day counts the calendars meet on. Every calendar here is a way of naming a
 * Julian Day Number — the count of whole days since 1 January 4713 BC
 * (Julian) — so converting between any two goes through one.
 *
 * Years are astronomical throughout: 0 is 1 BC, −1 is 2 BC.
 */

const MS_PER_DAY = 86_400_000;
/** JDN of 1 January 1970, the day `Date` counts from. */
const JDN_UNIX_EPOCH = 2_440_588;

export interface YearMonthDay {
	year: number;
	/** 1-based. */
	month: number;
	day: number;
}

/** JDN of a proleptic Gregorian date. Through `Date`, whose own calendar it is,
 *  so the whole range `Date` reaches works without a formula of our own. */
export function gregorianToJdn(year: number, month: number, day: number): number {
	const date = new Date(0);
	date.setUTCFullYear(year, month - 1, day);
	return Math.floor(date.getTime() / MS_PER_DAY) + JDN_UNIX_EPOCH;
}

export function jdnToGregorian(jdn: number): YearMonthDay {
	const date = new Date((jdn - JDN_UNIX_EPOCH) * MS_PER_DAY);
	return { year: date.getUTCFullYear(), month: date.getUTCMonth() + 1, day: date.getUTCDate() };
}

/** JDN of a proleptic Julian date (Fliegel & Van Flandern, floored throughout
 *  so it holds before 4713 BC too). */
export function julianToJdn(year: number, month: number, day: number): number {
	const a = Math.floor((14 - month) / 12);
	const y = year + 4800 - a;
	const m = month + 12 * a - 3;
	return day + Math.floor((153 * m + 2) / 5) + 365 * y + Math.floor(y / 4) - 32083;
}

export function jdnToJulian(jdn: number): YearMonthDay {
	const c = jdn + 32082;
	const d = Math.floor((4 * c + 3) / 1461);
	const e = c - Math.floor((1461 * d) / 4);
	const m = Math.floor((5 * e + 2) / 153);
	return {
		day: e - Math.floor((153 * m + 2) / 5) + 1,
		month: m + 3 - 12 * Math.floor(m / 10),
		year: d - 4800 + Math.floor(m / 10)
	};
}

/**
 * The day a `Date` falls on, as a JDN, in the zone it is being shown in. The
 * app shows instants in the reader's zone and calendar-only dates in UTC, so
 * those two are read straight off the `Date`; any other zone asks Intl.
 */
export function dateToJdn(date: Date, timeZone?: string): number {
	if (timeZone === undefined) {
		return gregorianToJdn(date.getFullYear(), date.getMonth() + 1, date.getDate());
	}
	if (timeZone === 'UTC') {
		return gregorianToJdn(date.getUTCFullYear(), date.getUTCMonth() + 1, date.getUTCDate());
	}
	const parts = new Intl.DateTimeFormat('en-US', {
		timeZone,
		year: 'numeric',
		month: 'numeric',
		day: 'numeric',
		era: 'short'
	}).formatToParts(date);
	const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
	const yearOfEra = Number(get('year'));
	const year = get('era').startsWith('B') ? 1 - yearOfEra : yearOfEra;
	return gregorianToJdn(year, Number(get('month')), Number(get('day')));
}

/** Local midnight starting the day `jdn`: what the timeline's ticks sit on. */
export function jdnToLocalMidnight(jdn: number): Date {
	const { year, month, day } = jdnToGregorian(jdn);
	const date = new Date(2000, 0, 1);
	date.setFullYear(year, month - 1, day);
	date.setHours(0, 0, 0, 0);
	return date;
}

/** UTC noon of the day `jdn`: a moment safely inside that day whichever way
 *  a formatter reads it, for formatting a day rather than an instant. */
export function jdnToUtcNoon(jdn: number): Date {
	return new Date((jdn - JDN_UNIX_EPOCH) * MS_PER_DAY + MS_PER_DAY / 2);
}
