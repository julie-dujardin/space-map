import { getLocale } from '$lib/paraglide/runtime.js';
import { getSettings } from '$lib/state/settings.svelte';

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

function pad(n: number, width = 2): string {
	const s = String(Math.abs(n));
	return s.length >= width ? s : '0'.repeat(width - s.length) + s;
}

/**
 * Format a UTC Date as ISO 8601, omitting reduced-precision components
 * (month=0 / day=0). Honors `opts` to decide whether to emit the time portion.
 */
function formatIso8601(
	date: Date,
	{
		month,
		day,
		hasTime,
		hasSeconds = true
	}: { month: number; day: number; hasTime: boolean; hasSeconds?: boolean }
): string {
	const year = date.getUTCFullYear();
	const sign = year < 0 ? '-' : year > 9999 ? '+' : '';
	const yStr = pad(Math.abs(year), 4);
	let out = `${sign}${yStr}`;
	if (month > 0) out += `-${pad(date.getUTCMonth() + 1)}`;
	if (day > 0) out += `-${pad(date.getUTCDate())}`;
	if (hasTime) {
		out += `T${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`;
		// A source that wrote no seconds did not claim any.
		if (hasSeconds) out += `:${pad(date.getUTCSeconds())}`;
		out += 'Z';
	}
	return out;
}

function formatLocaleDate(d: Date, month: 'long' | 'short' = 'long'): string {
	const opts: Intl.DateTimeFormatOptions = { year: 'numeric', month, day: 'numeric' };
	// JS Date has no year 0; getUTCFullYear() < 1 means BCE (proleptic Gregorian).
	if (d.getUTCFullYear() < 1) opts.era = 'short';
	return d.toLocaleDateString(getLocale(), opts);
}

interface ParsedIsoDate {
	date: Date;
	month: number;
	day: number;
	isBCE: boolean;
	hasTime: boolean;
	/** Whether the string carried a seconds field at all. */
	hasSeconds: boolean;
}

/**
 * Parse an ISO 8601 date string into its components. Handles plain dates
 * ("2024-01-15"), ISO datetimes ("2024-01-15T00:00:00Z"), Wikidata-style
 * signed strings ("+1801-01-01T00:00:00Z", "-0466-00-00T00:00:00Z"), and
 * truncated forms ("2024", "2024-06") where omitted components signal
 * unknown precision — equivalent to the Wikidata "00" placeholder. The
 * seconds field is optional ("2023-09-24T14:52Z").
 */
export function parseIsoDate(raw: string): ParsedIsoDate | null {
	const m = raw.match(
		/^([+-]?)(\d+)(?:-(\d{2})(?:-(\d{2}))?)?(?:T(\d{2}):(\d{2})(?::(\d{2}))?Z)?$/
	);
	if (!m) return null;
	const [, sign, yearStr, monthStr = '00', dayStr = '00', hh, mm, ss] = m;
	const isBCE = sign === '-';
	const yearAbs = parseInt(yearStr, 10);
	const month = parseInt(monthStr, 10);
	const day = parseInt(dayStr, 10);

	const date = new Date(0);
	date.setUTCFullYear(isBCE ? -yearAbs : yearAbs, (month || 1) - 1, day || 1);
	if (hh !== undefined) {
		date.setUTCHours(
			parseInt(hh, 10),
			parseInt(mm, 10),
			ss === undefined ? 0 : parseInt(ss, 10),
			0
		);
	}
	if (isNaN(date.getTime())) return null;

	const hasTime = hh !== undefined && (hh !== '00' || mm !== '00' || (ss ?? '00') !== '00');
	return { date, month, day, isBCE, hasTime, hasSeconds: ss !== undefined };
}

// Only a handful of option shapes exist, but the event lists call this per
// row; constructing an Intl.DateTimeFormat each time is the expensive part.
const dateTimeFormats = new Map<string, Intl.DateTimeFormat>();
function cachedDateTimeFormat(locale: string, opts: Intl.DateTimeFormatOptions) {
	const key = locale + JSON.stringify(opts);
	let format = dateTimeFormats.get(key);
	if (!format) dateTimeFormats.set(key, (format = new Intl.DateTimeFormat(locale, opts)));
	return format;
}

/**
 * Format an ISO 8601 date string as a localized date (or pass-through ISO,
 * depending on the user's date-format setting). See {@link parseIsoDate} for
 * accepted formats. Reduced-precision month/day (00) are omitted from
 * rendering; negative years render with the locale's era (locale mode) or a
 * minus sign (ISO mode).
 */
export function formatIsoDate(raw: string): string {
	const parsed = parseIsoDate(raw);
	if (!parsed) return raw;
	const { date, month, day, isBCE, hasTime, hasSeconds } = parsed;

	if (getSettings().resolvedDateFormat === 'iso') {
		return formatIso8601(date, { month, day, hasTime, hasSeconds });
	}

	const opts: Intl.DateTimeFormatOptions = { year: 'numeric' };
	if (month > 0) opts.month = 'long';
	if (day > 0) opts.day = 'numeric';
	if (isBCE) opts.era = 'short';
	// Calendar-only inputs (no time component) are anchored to UTC midnight by
	// convention; render them in UTC so the encoded date isn't shifted by the
	// browser's offset. Time-bearing inputs are real instants and use local TZ.
	if (!hasTime) opts.timeZone = 'UTC';

	const dateStr = cachedDateTimeFormat(getLocale(), opts).format(date);
	if (!hasTime || month === 0 || day === 0) return dateStr;
	const timeOpts: Intl.DateTimeFormatOptions = {
		hour12: getSettings().resolvedHour12,
		hour: 'numeric',
		minute: '2-digit'
	};
	if (hasSeconds) timeOpts.second = '2-digit';
	const timeStr = date.toLocaleTimeString(getLocale(), timeOpts);
	return `${dateStr} ${timeStr}`;
}

/**
 * Format an IAU name-approval date, dropping the day the gazetteer invented.
 *
 * Year-only records are stamped 1 January — 87 % of the gazetteer, including
 * every one of the 7 278 features approved in the 2006 bulk pass. No real
 * dated approval falls on 1 January (the next-commonest day carries 57), so
 * the date is safe to read as year-only.
 */
export function formatApprovalDate(raw: string): string {
	return formatIsoDate(raw.endsWith('-01-01') ? raw.slice(0, 4) : raw);
}

/** Format a Julian Date (TDB) as a localized date string (or ISO 8601 date). */
export function formatJulianDate(jd: number): string {
	const d = jdToDate(jd);
	if (getSettings().resolvedDateFormat === 'iso') {
		return formatIso8601(d, { month: 1, day: 1, hasTime: false });
	}
	return formatLocaleDate(d, 'short');
}

/**
 * Format a Julian Date as a localized date+time string, honoring the user's
 * date-format and clock settings. Used by the simulator's time bar.
 */
export function formatJulianDateTime(jd: number, opts: Intl.DateTimeFormatOptions): string {
	const d = jdToDate(jd);
	const settings = getSettings();
	if (settings.resolvedDateFormat === 'iso') {
		// Local-time ISO: yyyy-mm-dd hh:mm (24h, since ISO doesn't define a 12h form).
		const hasTime = opts.hour !== undefined || opts.minute !== undefined;
		const datePart = `${pad(d.getFullYear(), 4)}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
		if (!hasTime) return datePart;
		const timePart = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
		return `${datePart} ${timePart}`;
	}
	const merged: Intl.DateTimeFormatOptions = { ...opts };
	if (opts.hour !== undefined) merged.hour12 = settings.resolvedHour12;
	return d.toLocaleString(getLocale(), merged);
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
