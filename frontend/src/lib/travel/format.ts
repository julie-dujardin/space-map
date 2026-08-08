/**
 * Presentation helpers for the travel panel. Kept out of the components so the
 * rounding rules are testable and stated once.
 */

import * as m from '$lib/paraglide/messages.js';
import { formatNumber } from '$lib/format/quantities';

const DAYS_PER_MONTH = 30.44;
const MONTHS_PER_YEAR = 12;

/**
 * A cruise length as a person would say it. Rounding the smaller unit can land
 * on a full one of the larger, so each carry is explicit — "3 mo 30 d" is not a
 * duration anyone writes.
 *
 * Past a year it switches to years and months: nobody reads "45 mo 25 d", and
 * the long form outgrows the stat tile it sits in.
 */
export function formatTripTime(days: number): string {
	if (!Number.isFinite(days) || days < 0) return '—';

	const months = Math.floor(days / DAYS_PER_MONTH);
	if (months >= MONTHS_PER_YEAR) {
		const years = Math.floor(months / MONTHS_PER_YEAR);
		const restMonths = months % MONTHS_PER_YEAR;
		if (restMonths === 0) return m.travel_years({ count: formatNumber(years) });
		return m.travel_years_months({
			years: formatNumber(years),
			months: formatNumber(restMonths)
		});
	}

	const rest = Math.round(days - months * DAYS_PER_MONTH);
	if (months === 0) return m.travel_days({ count: formatNumber(rest) });
	if (rest >= 30) {
		const carried = months + 1;
		return carried >= MONTHS_PER_YEAR
			? m.travel_years({ count: formatNumber(1) })
			: m.travel_months({ count: formatNumber(carried) });
	}
	if (rest === 0) return m.travel_months({ count: formatNumber(months) });
	return m.travel_months_days({ months: formatNumber(months), days: formatNumber(rest) });
}

/** Δv with two decimals — the precision the estimates actually carry. */
export function formatDv(kms: number): string {
	if (!Number.isFinite(kms)) return '—';
	return m.travel_unit_km_s({ value: kms.toFixed(2) });
}

/** One-way light time across a distance in km. */
export function formatSignalDelay(seconds: number): string {
	if (!Number.isFinite(seconds) || seconds < 0) return '—';
	const minutes = Math.floor(seconds / 60);
	const rest = Math.round(seconds - minutes * 60);
	if (minutes === 0) return m.travel_seconds({ count: formatNumber(rest) });
	return m.travel_minutes_seconds({
		minutes: formatNumber(minutes),
		seconds: String(rest).padStart(2, '0')
	});
}
