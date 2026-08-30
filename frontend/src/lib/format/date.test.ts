import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: () => 'en-US' }));

import { dateToJD, jdToDate, formatIsoDate, formatJulianDate } from './date';

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

describe('formatIsoDate', () => {
	it.each([
		{ name: 'leading + at midnight', raw: '+1801-01-01T00:00:00Z', expected: 'January 1, 1801' },
		{
			name: 'non-midnight with time',
			raw: '+2024-06-15T14:30:00Z',
			expected: 'June 15, 2024 2:30:00 PM'
		},
		{ name: 'unsigned ISO datetime', raw: '2024-01-01T00:00:00Z', expected: 'January 1, 2024' },
		{ name: 'plain date without time', raw: '2024-01-01', expected: 'January 1, 2024' },
		// Wikidata reduced precision: month=00 / day=00 mean the lower components are unknown.
		{ name: 'year-only modern', raw: '+2024-00-00T00:00:00Z', expected: '2024' },
		{ name: 'month-only modern', raw: '+1980-06-00T00:00:00Z', expected: 'June 1980' },
		// BCE: ISO year 0 = 1 BCE, so -0466 renders as 467 BC, -0099 as 100 BC.
		{
			name: 'BCE year-only (Halley first sighting)',
			raw: '-0466-00-00T00:00:00Z',
			expected: '467 BC'
		},
		{ name: 'BCE full precision', raw: '-0099-03-15T00:00:00Z', expected: 'March 15, 100 BC' },
		// Early-AD year-only (e.g. early Halley apparition)
		{ name: 'early-AD year-only', raw: '+0240-00-00T00:00:00Z', expected: '240' },
		// Truncated forms (Commons-image dates from the data exporter)
		{ name: 'truncated year', raw: '2009', expected: '2009' },
		{ name: 'truncated year-month', raw: '2009-10', expected: 'October 2009' },
		{ name: 'signed truncated year', raw: '+2009', expected: '2009' },
		// SBDB stores ancient observation dates with 3-digit unpadded years
		// (e.g. C/568 O1 → "568-11-05"); parser must accept <4-digit years.
		{ name: '3-digit-year SBDB date', raw: '568-11-05', expected: 'November 5, 568' },
		{ name: '3-digit-year BCE SBDB date', raw: '-43-05-30', expected: 'May 30, 44 BC' },
		// Probe events are written to the precision the sources have; a record
		// with no seconds must not be rendered as though it had them.
		{
			name: 'minute-precision event date',
			raw: '2023-09-24T14:52Z',
			expected: 'September 24, 2023 2:52 PM'
		},
		{
			name: 'second-precision event date',
			raw: '1969-07-20T20:17:40Z',
			expected: 'July 20, 1969 8:17:40 PM'
		}
	])('$name → $expected', ({ raw, expected }) => {
		expect(formatIsoDate(raw)).toBe(expected);
	});

	it('returns raw string when unparseable', () => {
		expect(formatIsoDate('not a date')).toBe('not a date');
	});
});

describe('formatJulianDate', () => {
	it('formats J2000 as a readable date', () => {
		const result = formatJulianDate(2451545.0);
		expect(result).toContain('2000');
	});

	// BCE Julian dates (e.g. orbit epoch for C/-43 K1) must include the era
	// marker — otherwise "44 BC" renders as a bare "44" indistinguishable from AD.
	it('formats a BCE Julian date with era', () => {
		// JD 1705532.5 = -0043-06-26 (proleptic Gregorian) = 44 BC.
		const result = formatJulianDate(1705532.5);
		expect(result).toContain('44');
		expect(result).toContain('BC');
	});
});
