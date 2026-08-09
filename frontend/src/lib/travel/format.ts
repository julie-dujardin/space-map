/**
 * Presentation helpers for the travel panel. Kept out of the components so the
 * rounding rules are testable and stated once.
 *
 * The units themselves are spelled by `Intl.DurationFormat`, so every locale
 * gets its own abbreviations and its own order without a message key each.
 */

import * as m from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';

const DAYS_PER_MONTH = 30.44;
const MONTHS_PER_YEAR = 12;
const HOURS_PER_DAY = 24;
const MINUTES_PER_HOUR = 60;
const SECONDS_PER_MINUTE = 60;

/** The stat tile fits one short line; every route prints its dates beside it. */
const NARROW: Intl.DurationFormatOptions = { style: 'narrow' };

/** Zero fields are dropped, so a duration of nothing needs its unit named. */
const NARROW_ZERO: Intl.DurationFormatOptions = { ...NARROW, minutesDisplay: 'always' };

function say(duration: Intl.Duration): string {
	const locale = getLocale();
	return (
		new Intl.DurationFormat(locale, NARROW).format(duration) ||
		new Intl.DurationFormat(locale, NARROW_ZERO).format({ minutes: 0 })
	);
}

/**
 * The two largest units that carry anything: an interplanetary transfer runs in
 * months and days, a rendezvous in low orbit in hours and minutes. Rounding the
 * smaller unit can land on a full one of the larger, so each carry is explicit
 * — "3 mo 30 d" is not a duration anyone writes.
 *
 * Past a year it stops at years and months: nobody reads "45 mo 25 d", and the
 * long form outgrows the stat tile it sits in. Minutes are the floor at the
 * other end — a trip quoted in seconds is a launch profile, not a journey.
 */
export function tripDuration(days: number): Intl.Duration {
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
	const minutes = Math.round((totalHours - hours) * MINUTES_PER_HOUR);
	if (minutes < MINUTES_PER_HOUR) return { hours, minutes };
	return hours + 1 >= HOURS_PER_DAY ? { days: 1 } : { hours: hours + 1 };
}

/** A cruise length as a person would say it. */
export function formatTripTime(days: number): string {
	if (!Number.isFinite(days) || days < 0) return '—';
	return say(tripDuration(days));
}

/** A torch drive's budget runs to six figures of km/s, which fits nowhere it
 *  is printed; from here the unit climbs to Mm/s. */
const MEGAMETRE_FLOOR_KMS = 10_000;

/** Three significant figures for the climbed unit — 62.5, 125, 1250. */
function megametres(kms: number): string {
	return Number((kms / 1000).toPrecision(3)).toString();
}

/** Δv with two decimals — the precision the estimates actually carry. */
export function formatDv(kms: number): string {
	if (!Number.isFinite(kms)) return '—';
	if (kms >= MEGAMETRE_FLOOR_KMS) return m.travel_unit_mm_s({ value: megametres(kms) });
	return m.travel_unit_km_s({ value: kms.toFixed(2) });
}

/** The route row's tighter form: one decimal, same unit climb. */
export function formatDvBrief(kms: number): string {
	if (!Number.isFinite(kms)) return '—';
	if (kms >= MEGAMETRE_FLOOR_KMS) return m.travel_unit_mm_s({ value: megametres(kms) });
	return m.travel_unit_km_s({ value: kms.toFixed(1) });
}

/** Figure and unit split apart, for the stat tile that sets its own type. */
export function dvParts(kms: number): { value: string; unit: string } {
	if (!Number.isFinite(kms)) return { value: '—', unit: '' };
	if (kms >= MEGAMETRE_FLOOR_KMS) return { value: megametres(kms), unit: m.travel_mm_s() };
	return { value: kms.toFixed(1), unit: m.travel_km_s() };
}

/** Standard gravity, m/s² — the unit every torch drive in fiction is quoted in. */
const G0_M_S2 = 9.80665;
/** Below this a multiple of a gravity is four leading zeros and no meaning. An
 *  ion drive is a hundredth of this, and reads better in its own unit. */
const GRAVITIES_FLOOR = 0.01;

/** Two significant figures, which is all any of these are known to. */
function significant(value: number): string {
	return Number(value.toPrecision(2)).toString();
}

/**
 * The acceleration a drive holds, in the unit that makes it mean something: a
 * fraction of a gravity for anything you could stand up in, m/s² for the slow
 * drives where that fraction stops being a number anyone can picture.
 */
export function formatAcceleration(accelMs2: number): string {
	if (!Number.isFinite(accelMs2) || accelMs2 <= 0) return '—';
	const gravities = accelMs2 / G0_M_S2;
	if (gravities < GRAVITIES_FLOOR) {
		return `${significant(accelMs2)} ${m.unit_symbol_metres_per_second_squared()}`;
	}
	return m.travel_unit_g({ value: significant(gravities) });
}

const LIGHT_SPEED_KMS = 299792.458;
/** Below a hundredth of c the fraction is noise; above it, km/s is the noise —
 *  nobody can place 6,500 km/s, and "2.2% c" is the same fact placed. */
const LIGHT_FRACTION_FLOOR = 0.01;

/** The speed as a percentage of c once it is at least 1% of it, else null. */
export function lightPercent(kms: number): string | null {
	if (!Number.isFinite(kms)) return null;
	const fraction = kms / LIGHT_SPEED_KMS;
	return fraction >= LIGHT_FRACTION_FLOOR ? significant(fraction * 100) : null;
}

/** A speed a craft is actually doing: km/s until it is a real fraction of c. */
export function formatSpeed(kms: number): string {
	const percent = lightPercent(kms);
	return percent !== null ? m.travel_unit_percent_c({ value: percent }) : formatDv(kms);
}

/** One-way light time across a distance in km. */
export function formatSignalDelay(seconds: number): string {
	if (!Number.isFinite(seconds) || seconds < 0) return '—';
	const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
	const rest = Math.round(seconds - minutes * SECONDS_PER_MINUTE);
	if (rest >= SECONDS_PER_MINUTE) return say({ minutes: minutes + 1 });
	return say({ minutes, seconds: rest });
}
