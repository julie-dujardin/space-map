import { getLocale } from '$lib/paraglide/runtime.js';

type DurationUnit = 'year' | 'day' | 'hour' | 'minute';

const DAYS_PER_YEAR = 365.25;

function pickUnit(days: number): DurationUnit {
	const abs = Math.abs(days);
	if (abs >= DAYS_PER_YEAR) return 'year';
	if (abs >= 1) return 'day';
	if (abs >= 1 / 24) return 'hour';
	return 'minute';
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
	}
}

/** Format a duration (in days) to a human-readable string with auto-selected unit. */
export function formatDuration(days: number): string {
	const unit = pickUnit(days);
	return new Intl.NumberFormat(getLocale(), {
		style: 'unit',
		unit,
		unitDisplay: 'long',
		maximumSignificantDigits: 3
	}).format(convert(days, unit));
}
