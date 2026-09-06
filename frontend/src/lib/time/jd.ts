/** JD ↔ Date/ET conversions and time constants shared across consumers. */

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

/** JD (TDB) → seconds past J2000 (ET). */
export function jdToEt(jd: number): number {
	return (jd - J2000_JD) * SECONDS_PER_DAY;
}

/** ET (TDB seconds past J2000) → Julian Date TDB. */
export function etToJd(et: number): number {
	return J2000_JD + et / SECONDS_PER_DAY;
}
