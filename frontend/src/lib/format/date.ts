import { getLocale } from '$lib/paraglide/runtime.js';

const JD_UNIX_EPOCH = 2440587.5;
const MS_PER_DAY = 86400000;

/** Convert a JS Date to Julian Date. */
export function dateToJD(date: Date): number {
	return date.getTime() / MS_PER_DAY + JD_UNIX_EPOCH;
}

/** Convert a Julian Date to a JS Date. */
export function jdToDate(jd: number): Date {
	return new Date((jd - JD_UNIX_EPOCH) * MS_PER_DAY);
}

function formatDate(d: Date, month: 'long' | 'short' = 'long'): string {
	return d.toLocaleDateString(getLocale(), {
		timeZone: 'UTC',
		year: 'numeric',
		month,
		day: 'numeric'
	});
}

/**
 * Format a Wikidata/Wikipedia ISO 8601 date string as a localized date.
 * - Strips leading '+' (e.g. "+1801-01-01T00:00:00Z")
 * - When time is midnight, returns a localized date string (e.g. "January 1, 1801")
 * - When time is non-zero, returns "<localized date> <localized time>"
 */
export function formatWikidataDate(raw: string): string {
	const s = raw.startsWith('+') ? raw.slice(1) : raw;
	const tIdx = s.indexOf('T');
	if (tIdx === -1) return s;
	const date = s.slice(0, tIdx);
	const time = s.slice(tIdx + 1);
	const d = new Date(date + 'T' + time);
	const localDate = formatDate(d);
	if (time === '00:00:00Z') return localDate;
	const localTime = d.toLocaleTimeString(getLocale(), { timeZone: 'UTC' });
	return `${localDate} ${localTime}`;
}

/** Format a Julian Date (TDB) as a localized date string. */
export function formatJulianDate(jd: number): string {
	return formatDate(jdToDate(jd), 'short');
}
