/** JD↔ET helpers and time constants shared across consumers. */

export const J2000_JD = 2451545.0;
export const SECONDS_PER_DAY = 86400;
export const DAYS_PER_YEAR = 365.25;

/** JD (TDB) → seconds past J2000 (ET). */
export function jdToEt(jd: number): number {
	return (jd - J2000_JD) * SECONDS_PER_DAY;
}

/** ET (TDB seconds past J2000) → Julian Date TDB. */
export function etToJd(et: number): number {
	return J2000_JD + et / SECONDS_PER_DAY;
}
