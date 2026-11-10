import { describe, it, expect } from 'vitest';
import { J2000_JD, dateToJD, jdToDate, tdbToUtc, utcToTdb } from './jd';

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
	// TDB − UTC from SPICE `str2et` with naif0012.tls, inside the leap-second table.
	it.each([
		{ utc: '1972-01-01T00:00:00Z', s: 42.18392062187195 },
		{ utc: '1990-06-15T06:30:00Z', s: 57.184530675411224 },
		{ utc: '2016-12-31T23:59:58Z', s: 68.1839189529419 },
		{ utc: '2017-01-01T00:00:01Z', s: 69.18393522500992 },
		{ utc: '2026-10-14T12:00:00Z', s: 69.18236207962036 }
	])('$utc is $s s behind TDB', ({ utc, s }) => {
		const jd = dateToJD(new Date(utc));
		expect(Math.abs((utcToTdb(jd) - jd) * 86400 - s)).toBeLessThan(1e-4);
	});

	it.each([
		'1600-01-01T00:00:00Z',
		'1960-03-01T00:00:00Z',
		'1990-06-15T06:30:00Z',
		'2026-10-14T12:00:00Z',
		'2350-07-01T00:00:00Z',
		'2600-12-31T00:00:00Z'
	])('%s comes back from tdbToUtc', (utc) => {
		const jd = dateToJD(new Date(utc));
		expect(Math.abs(tdbToUtc(utcToTdb(jd)) - jd) * 86400).toBeLessThan(1e-6);
	});
});

/** Outside the table the clock is UT, and TT − UT is ΔT. */
describe('ΔT outside the leap-second table', () => {
	const offset = (iso: string): number => {
		const jd = dateToJD(new Date(iso));
		return (utcToTdb(jd) - jd) * 86400;
	};

	// Published ΔT (Morrison & Stephenson; Espenak & Meeus 2006, Table 1),
	// within the ±0.3 s that TDB − TT and the 1972 offset add.
	it.each([
		{ iso: '1600-01-01T00:00:00Z', dt: 120 },
		{ iso: '1700-01-01T00:00:00Z', dt: 8.8 },
		{ iso: '1800-01-01T00:00:00Z', dt: 13.7 },
		{ iso: '1900-01-01T00:00:00Z', dt: -2.8 },
		{ iso: '1950-01-01T00:00:00Z', dt: 29.1 }
	])('is $dt s at $iso', ({ iso, dt }) => {
		expect(Math.abs(offset(iso) - dt)).toBeLessThan(0.3);
	});

	it('joins the table at 1972 without a step', () => {
		expect(offset('1972-01-01T00:00:00Z') - offset('1971-12-31T23:59:59Z')).toBeLessThan(1e-3);
	});

	it('holds the last leap second up to 2027, then joins the long-term parabola without a step', () => {
		expect(offset('2026-12-31T23:59:59Z')).toBeCloseTo(69.184, 2);
		expect(offset('2027-01-01T00:00:01Z') - offset('2026-12-31T23:59:59Z')).toBeLessThan(1e-3);
		// Past 2150 it is the parabola itself: −20 + 32 ((y − 1820) / 100)².
		expect(offset('2600-01-01T00:00:00Z')).toBeCloseTo(-20 + 32 * 7.8 ** 2, -1);
	});

	it('holds past the canon, so far dates keep the pace of the clock', () => {
		const at = (year: number) => {
			const jd = J2000_JD + (year - 2000) * 365.25;
			return (utcToTdb(jd) - jd) * 86400;
		};
		expect(at(100_000)).toBeCloseTo(at(3000), 2);
		expect(at(-100_000)).toBeCloseTo(at(-1999), 2);
	});

	it('grows steadily from the hold to the parabola', () => {
		let last = offset('2027-01-01T00:00:00Z');
		for (let y = 2030; y <= 2600; y += 10) {
			const next = offset(`${y}-01-01T00:00:00Z`);
			expect(next).toBeGreaterThan(last);
			last = next;
		}
	});
});
