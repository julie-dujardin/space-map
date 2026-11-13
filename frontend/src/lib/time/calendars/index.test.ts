import { describe, expect, it } from 'vitest';

import { calendarDateFormat, calendarFields, FRENCH_REPUBLICAN, JULIAN } from './index';
import { gregorianToJdn, jdnToJulian, julianToJdn } from './day-number';

const utc = (y: number, m: number, d: number, h = 12) => {
	const date = new Date(Date.UTC(2000, 0, 1, h));
	date.setUTCFullYear(y, m - 1, d);
	return date;
};

describe('Julian day numbers', () => {
	it('puts the Gregorian reform where Rome did', () => {
		// Thursday 4 October 1582 (Julian) was followed by Friday 15 October (Gregorian).
		expect(gregorianToJdn(1582, 10, 15) - julianToJdn(1582, 10, 4)).toBe(1);
	});

	it('round-trips the Julian calendar, BC included', () => {
		for (const jdn of [0, 1_000_000, 1_721_424, 2_299_160, 2_460_000, -50_000]) {
			const { year, month, day } = jdnToJulian(jdn);
			expect(julianToJdn(year, month, day)).toBe(jdn);
		}
	});
});

describe('calendarDateFormat', () => {
	const DAY: Intl.DateTimeFormatOptions = {
		year: 'numeric',
		month: 'long',
		day: 'numeric',
		timeZone: 'UTC'
	};

	it('leaves the Gregorian as Intl has it', () => {
		expect(calendarDateFormat('en-US', 'gregory', DAY).format(utc(2026, 11, 13))).toBe(
			'November 13, 2026'
		);
	});

	it('hands the calendars Intl has to Intl', () => {
		expect(calendarDateFormat('en-US', 'hebrew', DAY).format(utc(2026, 11, 13))).toBe(
			'3 Kislev 5787'
		);
	});

	it('writes the Julian in the locale’s own Gregorian pattern', () => {
		// The Julian date of the reform's first Gregorian day.
		expect(calendarDateFormat('en-US', JULIAN, DAY).format(utc(1582, 10, 15))).toBe(
			'October 5, 1582'
		);
		expect(calendarDateFormat('fr', JULIAN, DAY).format(utc(1582, 10, 15))).toBe('5 octobre 1582');
	});

	it('keeps the time and weekday of the instant under a Julian date', () => {
		const format = calendarDateFormat('en-US', JULIAN, {
			...DAY,
			weekday: 'long',
			hour: 'numeric',
			minute: '2-digit',
			hour12: false
		});
		// Friday in both calendars: it is the same day.
		expect(format.format(utc(1582, 10, 15, 14))).toBe('Friday, October 5, 1582 at 14:00');
	});

	it('writes the Republican calendar with the time after it', () => {
		const format = calendarDateFormat('fr', FRENCH_REPUBLICAN, {
			...DAY,
			hour: '2-digit',
			minute: '2-digit',
			hour12: false
		});
		expect(format.format(utc(1799, 11, 9, 10))).toBe('18 brumaire an VIII 10:00');
	});

	it('spans a Gregorian year that two Hijri years share', () => {
		const format = calendarDateFormat('en-US', 'islamic-civil', {
			year: 'numeric',
			timeZone: 'UTC'
		});
		// Intl pads the dash with thin spaces.
		const range = format.formatRange(utc(2024, 1, 1), utc(2024, 12, 31)).replace(/\s/g, ' ');
		expect(range).toBe('1445 – 1446 AH');
	});
});

describe('calendarFields', () => {
	it('reads a Chinese leap month as a month of its own', () => {
		// 2025 had a leap sixth month, from 25 July.
		const before = calendarFields('chinese', gregorianToJdn(2025, 7, 24));
		const after = calendarFields('chinese', gregorianToJdn(2025, 7, 25));
		expect(after.day).toBe(1);
		expect(after.monthKey).not.toBe(before.monthKey);
		expect(after.year).toBe(2025);
	});
});
