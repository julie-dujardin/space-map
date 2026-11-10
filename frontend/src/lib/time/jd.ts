/**
 * JD ↔ Date/ET conversions and time constants shared across consumers.
 *
 * The app's JDs are UTC: the clock, event dates, trip dates and the URL all
 * come from `Date`. Ephemeris data is in TDB: Chebyshev segments, element
 * epochs, probe ET and attitude keyframes. TLE data is in UTC, like the clock.
 * A function that reads TDB data converts the JD it gets with {@link utcToTdb}.
 * A TDB date that goes back to the clock converts with {@link tdbToUtc}.
 */

export const J2000_JD = 2451545.0;
export const SECONDS_PER_DAY = 86400;
export const DAYS_PER_YEAR = 365.25;

const JD_UNIX_EPOCH = 2440587.5;
export const MS_PER_DAY = 86400000;

/** The first and the last Julian Date that a `Date` holds. They are 10⁸ days
 *  before and after the Unix epoch, in the years −271,821 and 275,760. */
export const FIRST_DATE_JD = JD_UNIX_EPOCH - 1e8;
export const LAST_DATE_JD = JD_UNIX_EPOCH + 1e8;

/** Unix epoch milliseconds → Julian Date. */
export function unixMsToJD(ms: number): number {
	return ms / MS_PER_DAY + JD_UNIX_EPOCH;
}

/** Convert a JS Date to Julian Date. */
export function dateToJD(date: Date): number {
	return unixMsToJD(date.getTime());
}

/** Convert a Julian Date to a JS Date. */
export function jdToDate(jd: number): Date {
	return new Date((jd - JD_UNIX_EPOCH) * MS_PER_DAY);
}

/** TT − TAI, seconds. */
const TT_MINUS_TAI = 32.184;

/** TAI − UTC from 1972 on (naif0012.tls, IERS Bulletin C): [JD UTC it starts, seconds]. */
const LEAP_SECONDS: readonly (readonly [number, number])[] = [
	[2441317.5, 10],
	[2441499.5, 11],
	[2441683.5, 12],
	[2442048.5, 13],
	[2442413.5, 14],
	[2442778.5, 15],
	[2443144.5, 16],
	[2443509.5, 17],
	[2443874.5, 18],
	[2444239.5, 19],
	[2444786.5, 20],
	[2445151.5, 21],
	[2445516.5, 22],
	[2446247.5, 23],
	[2447161.5, 24],
	[2447892.5, 25],
	[2448257.5, 26],
	[2448804.5, 27],
	[2449169.5, 28],
	[2449534.5, 29],
	[2450083.5, 30],
	[2450630.5, 31],
	[2451179.5, 32],
	[2453736.5, 33],
	[2454832.5, 34],
	[2456109.5, 35],
	[2457204.5, 36],
	[2457754.5, 37]
];

/** 2027-01-01, the first instant the table does not reach: IERS Bulletin C has
 *  ruled out a leap second before it, so TT − UTC is known up to here. */
const LEAP_TABLE_END_JD = 2461406.5;

const TT_MINUS_UTC_1972 = LEAP_SECONDS[0][1] + TT_MINUS_TAI;
const TT_MINUS_UTC_LAST = LEAP_SECONDS[LEAP_SECONDS.length - 1][1] + TT_MINUS_TAI;

/** Years since 1820, in centuries: the argument of the long-term parabola. */
function centuriesSince1820(year: number): number {
	return (year - 1820) / 100;
}

/** The span of Espenak & Meeus's canon. The parabola is an extrapolation that
 *  grows without bound, to a year of ΔT by AD 100,000, which would put a
 *  trip's planets a year off its dates: past the canon ΔT holds. */
const CANON_FIRST_YEAR = -1999;
const CANON_LAST_YEAR = 3000;

/** Morrison & Stephenson's long-term ΔT, seconds. */
function parabola(year: number): number {
	const u = centuriesSince1820(Math.min(CANON_LAST_YEAR, Math.max(CANON_FIRST_YEAR, year)));
	return -20 + 32 * u * u;
}

function poly(t: number, c: readonly number[]): number {
	let v = 0;
	for (let k = c.length - 1; k >= 0; k--) v = v * t + c[k];
	return v;
}

/** Espenak & Meeus (2006) ΔT = TT − UT before 1972, seconds. */
function espenakMeeus(year: number): number {
	if (year < -500) return parabola(year);
	if (year < 500) {
		const u = year / 100;
		return poly(u, [10583.6, -1014.41, 33.78311, -5.952053, -0.1798452, 0.022174192, 0.0090316521]);
	}
	if (year < 1600) {
		const u = (year - 1000) / 100;
		return poly(u, [1574.2, -556.01, 71.23472, 0.319781, -0.8503463, -0.005050998, 0.0083572073]);
	}
	if (year < 1700) return poly(year - 1600, [120, -0.9808, -0.01532, 1 / 7129]);
	if (year < 1800) {
		return poly(year - 1700, [8.83, 0.1603, -0.0059285, 0.00013336, -1 / 1174000]);
	}
	if (year < 1860) {
		return poly(
			year - 1800,
			[
				13.72, -0.332447, 0.0068612, 0.0041116, -0.00037436, 0.0000121272, -0.0000001699,
				0.000000000875
			]
		);
	}
	if (year < 1900) {
		return poly(year - 1860, [7.62, 0.5737, -0.251754, 0.01680668, -0.0004473624, 1 / 233174]);
	}
	if (year < 1920) return poly(year - 1900, [-2.79, 1.494119, -0.0598939, 0.0061966, -0.000197]);
	if (year < 1941) return poly(year - 1920, [21.2, 0.84493, -0.0761, 0.0020936]);
	if (year < 1961) return poly(year - 1950, [29.07, 0.407, -1 / 233, 1 / 2547]);
	return poly(year - 1975, [45.45, 1.067, -1 / 260, -1 / 718]);
}

function yearOf(jd: number): number {
	return 2000 + (jd - J2000_JD) / DAYS_PER_YEAR;
}

/** Shifts the polynomials onto the table at 1972, which they miss by 0.07 s. */
const EM_OFFSET_1972 = TT_MINUS_UTC_1972 - espenakMeeus(yearOf(LEAP_SECONDS[0][0]));

const TABLE_END_YEAR = yearOf(LEAP_TABLE_END_JD);
/** Takes the parabola down onto the table's last value, fading out by 2150 as
 *  Espenak & Meeus's own 2050–2150 bridge does. */
const BRIDGE_END_YEAR = 2150;
const BRIDGE_SLOPE =
	(parabola(TABLE_END_YEAR) - TT_MINUS_UTC_LAST) / (BRIDGE_END_YEAR - TABLE_END_YEAR);

/**
 * TT − clock, seconds, at a clock (UTC) JD. Inside the leap-second table it is
 * exact. Outside, the clock is taken as UT, which is what civil time kept
 * before 1972 and what it will drift with after: ΔT from Espenak & Meeus,
 * joined to the table without a step at both ends.
 */
function ttMinusUtc(jdUtc: number): number {
	if (jdUtc < LEAP_SECONDS[0][0]) return espenakMeeus(yearOf(jdUtc)) + EM_OFFSET_1972;
	if (jdUtc < LEAP_TABLE_END_JD) {
		for (let k = LEAP_SECONDS.length - 1; k >= 0; k--) {
			if (jdUtc >= LEAP_SECONDS[k][0]) return LEAP_SECONDS[k][1] + TT_MINUS_TAI;
		}
	}
	const year = yearOf(jdUtc);
	if (year >= BRIDGE_END_YEAR) return parabola(year);
	return parabola(year) - BRIDGE_SLOPE * (BRIDGE_END_YEAR - year);
}

/** TDB − TT, seconds: the periodic term of SPICE's DELTET. */
function tdbMinusTt(jd: number): number {
	const m = 6.239996 + 1.99096871e-7 * (jd - J2000_JD) * SECONDS_PER_DAY;
	return 1.657e-3 * Math.sin(m + 1.671e-2 * Math.sin(m));
}

/** UTC JD → TDB JD, as SPICE's `str2et` does it inside the leap-second table.
 *  An open bound (±∞) stays open. */
export function utcToTdb(jd: number): number {
	if (!Number.isFinite(jd)) return jd;
	const tt = jd + ttMinusUtc(jd) / SECONDS_PER_DAY;
	return tt + tdbMinusTt(tt) / SECONDS_PER_DAY;
}

/** TDB JD → UTC JD; the inverse of {@link utcToTdb}. */
export function tdbToUtc(jd: number): number {
	if (!Number.isFinite(jd)) return jd;
	const tt = jd - tdbMinusTt(jd) / SECONDS_PER_DAY;
	// ΔT is read at the UTC being solved for. It drifts far slower than the
	// clock, so each pass gains several digits.
	let utc = tt - ttMinusUtc(tt) / SECONDS_PER_DAY;
	for (let k = 0; k < 2; k++) utc = tt - ttMinusUtc(utc) / SECONDS_PER_DAY;
	return utc;
}

/** UTC JD → ET (TDB seconds past J2000). */
export function jdToEt(jd: number): number {
	return (utcToTdb(jd) - J2000_JD) * SECONDS_PER_DAY;
}

/** ET (TDB seconds past J2000) → TDB JD. */
export function etToTdbJd(et: number): number {
	return J2000_JD + et / SECONDS_PER_DAY;
}

/** TDB JD → ET (TDB seconds past J2000). */
export function tdbJdToEt(jd: number): number {
	return (jd - J2000_JD) * SECONDS_PER_DAY;
}
