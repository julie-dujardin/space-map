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

/** TAI − UTC at a UTC JD. SPICE uses one second less than the first entry before 1972. */
function taiMinusUtc(jdUtc: number): number {
	for (let k = LEAP_SECONDS.length - 1; k >= 0; k--) {
		if (jdUtc >= LEAP_SECONDS[k][0]) return LEAP_SECONDS[k][1];
	}
	return LEAP_SECONDS[0][1] - 1;
}

/** TDB − TT, seconds: the periodic term of SPICE's DELTET. */
function tdbMinusTt(jd: number): number {
	const m = 6.239996 + 1.99096871e-7 * (jd - J2000_JD) * SECONDS_PER_DAY;
	return 1.657e-3 * Math.sin(m + 1.671e-2 * Math.sin(m));
}

/** UTC JD → TDB JD, as SPICE's `str2et` does it. An open bound (±∞) stays open. */
export function utcToTdb(jd: number): number {
	if (!Number.isFinite(jd)) return jd;
	const tt = jd + (taiMinusUtc(jd) + TT_MINUS_TAI) / SECONDS_PER_DAY;
	return tt + tdbMinusTt(tt) / SECONDS_PER_DAY;
}

/** TDB JD → UTC JD; the inverse of {@link utcToTdb}. */
export function tdbToUtc(jd: number): number {
	if (!Number.isFinite(jd)) return jd;
	const tt = jd - tdbMinusTt(jd) / SECONDS_PER_DAY;
	const guess = tt - (taiMinusUtc(tt) + TT_MINUS_TAI) / SECONDS_PER_DAY;
	return tt - (taiMinusUtc(guess) + TT_MINUS_TAI) / SECONDS_PER_DAY;
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
