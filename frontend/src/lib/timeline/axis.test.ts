import { describe, expect, it } from 'vitest';

import { calendarFields, FRENCH_REPUBLICAN } from '$lib/time/calendars';
import { dateToJdn } from '$lib/time/calendars/day-number';
import { dateToJD } from '$lib/time/jd';
import { axisTicks } from './axis';

const jd = (y: number, m: number, d: number) => dateToJD(new Date(y, m - 1, d));

/** Whether the day before `jdn` is in another year of `calendar`. */
function startsYear(calendar: string, jdn: number): boolean {
	return calendarFields(calendar, jdn - 1).yearKey !== calendarFields(calendar, jdn).yearKey;
}

describe('axisTicks in other calendars', () => {
	it('puts Hijri year ticks on 1 Muharram, on round years', () => {
		const ticks = axisTicks(jd(2000, 1, 1), jd(2060, 1, 1), 6, 'islamic-umalqura');
		expect(ticks.length).toBeGreaterThanOrEqual(4);
		for (const tick of ticks) {
			const jdn = dateToJdn(tick.date);
			const fields = calendarFields('islamic-umalqura', jdn);
			expect(tick.unit).toBe('year');
			expect(fields.day).toBe(1);
			expect(startsYear('islamic-umalqura', jdn)).toBe(true);
			expect(fields.year % 10).toBe(0);
		}
	});

	it('puts Republican year ticks on 1 vendémiaire', () => {
		const ticks = axisTicks(jd(1790, 1, 1), jd(1830, 1, 1), 6, FRENCH_REPUBLICAN);
		expect(ticks.map((t) => calendarFields(FRENCH_REPUBLICAN, dateToJdn(t.date)))).toEqual(
			[0, 10, 20, 30].map((year) => expect.objectContaining({ year, monthKey: '1', day: 1 }))
		);
	});

	it('steps Hebrew months through a leap year, Adar I and II both', () => {
		// 5784 (2023–24) was a leap year of thirteen months.
		const ticks = axisTicks(jd(2023, 9, 1), jd(2024, 10, 15), 14, 'hebrew');
		const months = ticks.map((t) => calendarFields('hebrew', dateToJdn(t.date)));
		expect(months.every((f) => f.day === 1)).toBe(true);
		expect(months.map((f) => f.monthKey)).toEqual(expect.arrayContaining(['Adar I', 'Adar II']));
	});

	it('finds the Republican complementary days as a month of their own', () => {
		const ticks = axisTicks(jd(1799, 6, 1), jd(1800, 1, 1), 8, FRENCH_REPUBLICAN);
		const months = ticks.map((t) => calendarFields(FRENCH_REPUBLICAN, dateToJdn(t.date)));
		expect(months.map((f) => f.monthKey)).toContain('13');
		expect(months.every((f) => f.day === 1)).toBe(true);
	});

	it('keeps the Buddhist years round in their own numbering', () => {
		const ticks = axisTicks(jd(2000, 1, 1), jd(2060, 1, 1), 6, 'buddhist');
		for (const tick of ticks) expect((tick.date.getFullYear() + 543) % 10).toBe(0);
	});

	it('ends over spans no calendar was ever kept for', () => {
		for (const calendar of ['hebrew', 'islamic-civil', 'chinese', FRENCH_REPUBLICAN]) {
			const ticks = axisTicks(jd(-9000, 1, 1), jd(12000, 1, 1), 7, calendar);
			expect(ticks.length).toBeLessThanOrEqual(15);
		}
	});
});

describe('axisTicks across a few years', () => {
	it.each(['gregory', 'islamic-umalqura', 'hebrew', FRENCH_REPUBLICAN])(
		'ticks %s years, not a month name every five years',
		(calendar) => {
			const ticks = axisTicks(jd(2020, 1, 1), jd(2026, 1, 1), 7, calendar);
			expect(ticks.length).toBeGreaterThanOrEqual(4);
			expect(ticks.every((t) => t.unit === 'year')).toBe(true);
		}
	);
});

describe('axisTicks round years across an era', () => {
	it('rounds Minguo years before 1912 in their own count', () => {
		const ticks = axisTicks(jd(1800, 1, 1), jd(1860, 1, 1), 6, 'roc');
		expect(ticks.length).toBeGreaterThan(0);
		for (const tick of ticks) expect((1912 - tick.date.getFullYear()) % 10).toBe(0);
	});

	it('rounds BC years as they are written', () => {
		const ticks = axisTicks(jd(-600, 1, 1), jd(-300, 1, 1), 6, 'gregory');
		expect(ticks.length).toBeGreaterThan(0);
		// Astronomical −499 is 500 BC.
		for (const tick of ticks) expect((1 - tick.date.getFullYear()) % 50).toBe(0);
	});
});
