import { getLocale } from '$lib/paraglide/runtime.js';
import { precisionOptions } from './quantities';

type DurationUnit = 'year' | 'day' | 'hour' | 'minute' | 'second';

const DAYS_PER_YEAR = 365.25;

function pickUnit(days: number): DurationUnit {
	const abs = Math.abs(days);
	if (abs >= DAYS_PER_YEAR) return 'year';
	if (abs >= 1) return 'day';
	if (abs >= 1 / 24) return 'hour';
	if (abs >= 1 / 1440) return 'minute';
	return 'second';
}

function convert(days: number, to: DurationUnit): number {
	switch (to) {
		case 'year':
			return days / DAYS_PER_YEAR;
		case 'day':
			return days;
		case 'hour':
			return days * 24;
		case 'minute':
			return days * 24 * 60;
		case 'second':
			return days * 24 * 60 * 60;
	}
}

/** Format a duration (in days) to a human-readable string with auto-selected unit. */
export function formatDuration(days: number): string {
	const unit = pickUnit(days);
	const value = convert(days, unit);
	return new Intl.NumberFormat(getLocale(), {
		style: 'unit',
		unit,
		unitDisplay: 'long',
		...precisionOptions(value)
	}).format(value);
}

const DAYS_PER_MONTH = 30.44;
const MONTHS_PER_YEAR = 12;
const HOURS_PER_DAY = 24;
const MINUTES_PER_HOUR = 60;
const SECONDS_PER_MINUTE = 60;
/** For the callers that hold their duration in seconds, like a light delay. */
export const SECONDS_PER_DAY = HOURS_PER_DAY * MINUTES_PER_HOUR * SECONDS_PER_MINUTE;

/** The stat tile fits one short line; every route prints its dates beside it. */
const NARROW: Intl.DurationFormatOptions = { style: 'narrow' };

/** Zero fields are dropped, so a duration of nothing needs its unit named. */
const NARROW_ZERO: Intl.DurationFormatOptions = { ...NARROW, secondsDisplay: 'always' };

function say(duration: Intl.Duration): string {
	const locale = getLocale();
	return (
		new Intl.DurationFormat(locale, NARROW).format(duration) ||
		new Intl.DurationFormat(locale, NARROW_ZERO).format({ seconds: 0 })
	);
}

/**
 * The two largest units that carry anything: an interplanetary transfer runs in
 * months and days, a rendezvous in low orbit in hours and minutes, a signal
 * delay maybe in seconds alone. Rounding the smaller unit can land on a full
 * one of the larger, so each carry is explicit — "3 mo 30 d" is not a duration
 * anyone writes.
 *
 * Past a year it stops at years and months: nobody reads "45 mo 25 d", and the
 * long form outgrows the stat tile it sits in.
 */
export function durationUnits(days: number): Intl.Duration {
	const months = Math.floor(days / DAYS_PER_MONTH);
	if (months >= MONTHS_PER_YEAR) {
		return { years: Math.floor(months / MONTHS_PER_YEAR), months: months % MONTHS_PER_YEAR };
	}

	if (months > 0) {
		const rest = Math.round(days - months * DAYS_PER_MONTH);
		if (rest < 30) return { months, days: rest };
		return months + 1 >= MONTHS_PER_YEAR ? { years: 1 } : { months: months + 1 };
	}

	const wholeDays = Math.floor(days);
	if (wholeDays > 0) {
		const hours = Math.round((days - wholeDays) * HOURS_PER_DAY);
		return hours < HOURS_PER_DAY ? { days: wholeDays, hours } : { days: wholeDays + 1 };
	}

	const totalHours = days * HOURS_PER_DAY;
	const hours = Math.floor(totalHours);
	if (hours > 0) {
		const minutes = Math.round((totalHours - hours) * MINUTES_PER_HOUR);
		if (minutes < MINUTES_PER_HOUR) return { hours, minutes };
		return hours + 1 >= HOURS_PER_DAY ? { days: 1 } : { hours: hours + 1 };
	}

	const totalMinutes = totalHours * MINUTES_PER_HOUR;
	const minutes = Math.floor(totalMinutes);
	const seconds = Math.round((totalMinutes - minutes) * SECONDS_PER_MINUTE);
	if (seconds < SECONDS_PER_MINUTE) return { minutes, seconds };
	return minutes + 1 >= MINUTES_PER_HOUR ? { hours: 1 } : { minutes: minutes + 1 };
}

/**
 * A length of time as a person would say it, years down to seconds — "3mo 12d",
 * "9d 1h", "1m 23s". The compound form for tiles and rows; `formatDuration`
 * above rounds to a single spelled-out unit for prose. Units come from
 * `Intl.DurationFormat`, so every locale gets its own abbreviations and order
 * without a message key each.
 */
export function formatDurationNarrow(days: number): string {
	if (!Number.isFinite(days) || days < 0) return '—';
	return say(durationUnits(days));
}
