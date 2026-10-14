import { describe, it, expect } from 'vitest';
import { dateToJD, jdToDate, tdbToUtc, utcToTdb } from './jd';

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

describe('utcToTdb', () => {
	// TDB − UTC from SPICE `str2et` with naif0012.tls.
	it.each([
		{ utc: '1960-03-01T00:00:00Z', s: 41.18539524078369 },
		{ utc: '1971-12-31T23:59:00Z', s: 41.18391704559326 },
		{ utc: '1972-01-01T00:00:00Z', s: 42.18392062187195 },
		{ utc: '1990-06-15T06:30:00Z', s: 57.184530675411224 },
		{ utc: '2016-12-31T23:59:58Z', s: 68.1839189529419 },
		{ utc: '2017-01-01T00:00:01Z', s: 69.18393522500992 },
		{ utc: '2026-10-14T12:00:00Z', s: 69.18236207962036 },
		{ utc: '2049-12-31T00:00:00Z', s: 69.18388438224792 }
	])('$utc is $s s behind TDB', ({ utc, s }) => {
		const jd = dateToJD(new Date(utc));
		expect(Math.abs((utcToTdb(jd) - jd) * 86400 - s)).toBeLessThan(1e-4);
	});

	it.each(['1960-03-01T00:00:00Z', '1990-06-15T06:30:00Z', '2026-10-14T12:00:00Z'])(
		'%s comes back from tdbToUtc',
		(utc) => {
			const jd = dateToJD(new Date(utc));
			expect(Math.abs(tdbToUtc(utcToTdb(jd)) - jd) * 86400).toBeLessThan(1e-4);
		}
	);
});
