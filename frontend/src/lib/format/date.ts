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
		year: 'numeric',
		month,
		day: 'numeric'
	});
}

/**
 * Format an ISO 8601 date string as a localized date. Handles plain dates
 * ("2024-01-15"), ISO datetimes ("2024-01-15T00:00:00Z"), and Wikidata-style
 * signed strings ("+1801-01-01T00:00:00Z", "-0466-00-00T00:00:00Z"). Wikidata
 * reduced-precision values encode unknown month/day as 00; those components
 * are omitted from the rendering. Negative years render with the locale's era.
 */
export function formatIsoDate(raw: string): string {
	const m = raw.match(/^([+-]?)(\d{4,})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}):(\d{2})Z)?$/);
	if (!m) return raw;
	const [, sign, yearStr, monthStr, dayStr, hh, mm, ss] = m;
	const isBCE = sign === '-';
	const yearAbs = parseInt(yearStr, 10);
	const month = parseInt(monthStr, 10);
	const day = parseInt(dayStr, 10);

	const d = new Date(0);
	d.setUTCFullYear(isBCE ? -yearAbs : yearAbs, (month || 1) - 1, day || 1);
	if (hh !== undefined) {
		d.setUTCHours(parseInt(hh, 10), parseInt(mm, 10), parseInt(ss, 10), 0);
	}
	if (isNaN(d.getTime())) return raw;

	const hasTime = hh !== undefined && (hh !== '00' || mm !== '00' || ss !== '00');
	const opts: Intl.DateTimeFormatOptions = { year: 'numeric' };
	if (month > 0) opts.month = 'long';
	if (day > 0) opts.day = 'numeric';
	if (isBCE) opts.era = 'short';
	// Calendar-only inputs (no time component) are anchored to UTC midnight by
	// convention; render them in UTC so the encoded date isn't shifted by the
	// browser's offset. Time-bearing inputs are real instants and use local TZ.
	if (!hasTime) opts.timeZone = 'UTC';

	const dateStr = new Intl.DateTimeFormat(getLocale(), opts).format(d);
	if (!hasTime || month === 0 || day === 0) return dateStr;
	const timeStr = d.toLocaleTimeString(getLocale());
	return `${dateStr} ${timeStr}`;
}

/** Format a Julian Date (TDB) as a localized date string. */
export function formatJulianDate(jd: number): string {
	return formatDate(jdToDate(jd), 'short');
}

/** Format a Julian Date relative to a reference JD as a localized "X ago" / "in X" string. */
export function formatJulianDateRelative(jd: number, refJd: number): string {
	const days = jd - refJd;
	const abs = Math.abs(days);
	let unit: Intl.RelativeTimeFormatUnit;
	let value: number;
	if (abs >= 365.25) {
		unit = 'year';
		value = days / 365.25;
	} else if (abs >= 30.4375) {
		unit = 'month';
		value = days / 30.4375;
	} else if (abs >= 1) {
		unit = 'day';
		value = days;
	} else if (abs >= 1 / 24) {
		unit = 'hour';
		value = days * 24;
	} else {
		unit = 'minute';
		value = days * 24 * 60;
	}
	return new Intl.RelativeTimeFormat(getLocale(), { numeric: 'auto' }).format(
		Math.round(value),
		unit
	);
}
