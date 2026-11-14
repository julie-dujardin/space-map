/**
 * Julian Day Numbers, which every calendar here converts through. Years are
 * astronomical: 0 is 1 BC.
 */

import { jdToDate } from '$lib/time/jd';

export interface YearMonthDay {
	year: number;
	/** 1-based. */
	month: number;
	day: number;
}

/** JDN of a proleptic Gregorian date (Fliegel & Van Flandern). Not through
 *  `Date`, which cannot hold the local day of its own first instant. */
export function gregorianToJdn(year: number, month: number, day: number): number {
	const a = Math.floor((14 - month) / 12);
	const y = year + 4800 - a;
	const m = month + 12 * a - 3;
	return (
		day +
		Math.floor((153 * m + 2) / 5) +
		365 * y +
		Math.floor(y / 4) -
		Math.floor(y / 100) +
		Math.floor(y / 400) -
		32045
	);
}

export function jdnToGregorian(jdn: number): YearMonthDay {
	const a = jdn + 32044;
	const b = Math.floor((4 * a + 3) / 146097);
	const c = a - Math.floor((146097 * b) / 4);
	const d = Math.floor((4 * c + 3) / 1461);
	const e = c - Math.floor((1461 * d) / 4);
	const m = Math.floor((5 * e + 2) / 153);
	return {
		day: e - Math.floor((153 * m + 2) / 5) + 1,
		month: m + 3 - 12 * Math.floor(m / 10),
		year: 100 * b + d - 4800 + Math.floor(m / 10)
	};
}

/** JDN of a proleptic Julian date (Fliegel & Van Flandern, floored to hold
 *  before 4713 BC). */
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

/** The day a `Date` falls on, as a JDN, in the zone it is shown in. */
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

/** UTC noon of the day `jdn`, inside that day whichever zone reads it. */
export function jdnToUtcNoon(jdn: number): Date {
	return jdToDate(jdn);
}
