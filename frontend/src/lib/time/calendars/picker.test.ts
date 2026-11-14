import { describe, expect, it } from 'vitest';
import { getDayOfWeek, startOfMonth } from '@internationalized/date';

import { FRENCH_REPUBLICAN, formatDecimalTime } from './index';
import {
	extendedYear,
	fromPickerDate,
	pickerCalendar,
	toPickerDate,
	withExtendedYear,
	yearLabel
} from './picker';
import { scannerFor } from './scan';

describe('the picker’s calendars', () => {
	it('lays out the Republican year: twelve months of thirty, then the complementary days', () => {
		const brumaire = toPickerDate(1799, 11, 9, FRENCH_REPUBLICAN);
		expect([brumaire.year, brumaire.month, brumaire.day]).toEqual([8, 2, 18]);
		const calendar = pickerCalendar(FRENCH_REPUBLICAN);
		expect(calendar.getMonthsInYear(brumaire)).toBe(13);
		expect(calendar.getDaysInMonth(brumaire)).toBe(30);
		// Year VII was sextile: six complementary days.
		expect(calendar.getDaysInMonth(toPickerDate(1799, 9, 20, FRENCH_REPUBLICAN))).toBe(6);
	});

	it('walks months across the year end and back to the same day', () => {
		const start = toPickerDate(2026, 9, 1, FRENCH_REPUBLICAN); // 15 fructidor CCXXXIV
		const next = start.add({ months: 2 });
		expect([next.year, next.month]).toEqual([235, 1]);
		expect(fromPickerDate(next.subtract({ months: 2 }))).toEqual({ year: 2026, month: 9, day: 1 });
	});

	it('counts years before the Republic down through its epoch', () => {
		const before = toPickerDate(1700, 1, 1, FRENCH_REPUBLICAN);
		expect(extendedYear(before)).toBe(-92);
		const moved = withExtendedYear(before, 3);
		expect(extendedYear(moved)).toBe(3);
		expect(fromPickerDate(withExtendedYear(moved, -92))).toEqual({ year: 1700, month: 1, day: 1 });
	});

	it('gives a Hebrew leap year its thirteen months', () => {
		expect(pickerCalendar('hebrew').getMonthsInYear(toPickerDate(2024, 1, 1, 'hebrew'))).toBe(13);
		expect(pickerCalendar('hebrew').getMonthsInYear(toPickerDate(2025, 1, 1, 'hebrew'))).toBe(12);
	});

	it('starts a Chinese leap month where the grid will draw it', () => {
		// The leap sixth month of 2025 began on 25 July.
		const leap = startOfMonth(toPickerDate(2025, 8, 1, 'chinese'));
		expect(fromPickerDate(leap)).toEqual({ year: 2025, month: 7, day: 25 });
		expect(leap.month).toBe(7);
	});

	it('keeps the weekday of the day it stands for', () => {
		// 9 November 1799 was a Saturday.
		expect(getDayOfWeek(toPickerDate(1799, 11, 9, FRENCH_REPUBLICAN), 'en-US')).toBe(6);
	});

	it('leaves calendars of Gregorian months on the Gregorian grid', () => {
		expect(pickerCalendar('buddhist').identifier).toBe('gregory');
		expect(toPickerDate(2026, 11, 13, 'japanese').month).toBe(11);
	});
});

describe('formatDecimalTime', () => {
	const at = (h: number, m: number, s = 0) => new Date(Date.UTC(2026, 10, 13, h, m, s));

	it.each([
		[0, 0, 0, '0:00:00'],
		[12, 0, 0, '5:00:00'],
		[6, 0, 0, '2:50:00'],
		[23, 59, 59, '9:99:98']
	])('writes %i:%i:%i as %s', (h, m, s, text) => {
		expect(formatDecimalTime(at(h, m, s), { seconds: true, timeZone: 'UTC' })).toBe(text);
	});

	it('drops the seconds unless asked', () => {
		expect(formatDecimalTime(at(18, 0), { timeZone: 'UTC' })).toBe('7:50');
	});
});

describe('the picker before a calendar’s epoch', () => {
	it.each([
		['coptic', 100, 6, 1],
		['ethiopic', -3000, 6, 1],
		['islamic-civil', 300, 3, 10],
		['hebrew', -4000, 9, 9]
	])('keeps %s on the day it was given (%i-%i-%i)', (calendar, y, m, d) => {
		expect(fromPickerDate(toPickerDate(y, m, d, calendar))).toEqual({ year: y, month: m, day: d });
	});
});

describe('yearLabel', () => {
	it.each(['chinese', 'dangi'])(
		'names every %s year in the picker’s range by its own number',
		(calendar) => {
			for (let year = 1400; year <= 2800; year += 7) {
				expect(yearLabel(calendar, 'en', year).startsWith(String(year))).toBe(true);
			}
		}
	);

	it('finds a Chinese year far from the anchor', () => {
		const scan = scannerFor('chinese');
		expect(scan.fields(scan.startOfYear(-3000)).year).toBe(-3000);
	});
});
