import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: () => 'en-US' }));

import { dateToJD, jdToDate, formatWikidataDate, formatJulianDate } from './date';

describe('dateToJD', () => {
	it.each([
		{ name: 'J2000 epoch', date: '2000-01-01T12:00:00Z', jd: 2451545.0 },
		{ name: 'Unix epoch', date: '1970-01-01T00:00:00Z', jd: 2440587.5 },
		{ name: 'J1900', date: '1900-01-01T12:00:00Z', jd: 2415021.0 }
	])('$name → JD $jd', ({ date, jd }) => {
		expect(dateToJD(new Date(date))).toBeCloseTo(jd, 5);
	});
});

describe('jdToDate', () => {
	it.each([
		{ name: 'J2000 epoch', jd: 2451545.0, iso: '2000-01-01T12:00:00.000Z' },
		{ name: 'Unix epoch', jd: 2440587.5, iso: '1970-01-01T00:00:00.000Z' }
	])('JD $jd → $iso', ({ jd, iso }) => {
		expect(jdToDate(jd).toISOString()).toBe(iso);
	});
});

describe('dateToJD / jdToDate round-trip', () => {
	it.each([
		'2000-01-01T12:00:00Z',
		'1969-07-20T20:17:00Z',
		'2024-06-15T08:30:00Z',
		'1900-01-01T00:00:00Z'
	])('%s survives round-trip within 1ms', (iso) => {
		const original = new Date(iso);
		const roundTripped = jdToDate(dateToJD(original));
		expect(Math.abs(roundTripped.getTime() - original.getTime())).toBeLessThanOrEqual(1);
	});
});

describe('formatWikidataDate', () => {
	it('formats a midnight date with leading +', () => {
		const result = formatWikidataDate('+1801-01-01T00:00:00Z');
		expect(result).toContain('1801');
		// Should not contain a time portion
		expect(result).not.toMatch(/\d{1,2}:\d{2}/);
	});

	it('formats a non-midnight date with time', () => {
		const result = formatWikidataDate('+2024-06-15T14:30:00Z');
		expect(result).toContain('2024');
		// Should contain a time portion
		expect(result).toMatch(/\d{1,2}:\d{2}/);
	});

	it('handles dates without leading +', () => {
		const result = formatWikidataDate('2024-01-01T00:00:00Z');
		expect(result).toContain('2024');
	});

	it('returns raw string when no T separator', () => {
		expect(formatWikidataDate('2024-01-01')).toBe('2024-01-01');
	});
});

describe('formatJulianDate', () => {
	it('formats J2000 as a readable date', () => {
		const result = formatJulianDate(2451545.0);
		expect(result).toContain('2000');
	});
});
