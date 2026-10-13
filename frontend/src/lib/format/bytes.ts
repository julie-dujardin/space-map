import { getLocale } from '$lib/paraglide/runtime.js';

const UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const;

/** "347 GB", "1.03 GB", "512 kB": decimal units, three significant digits. */
export function formatBytes(bytes: number): string {
	let value = bytes;
	let unit = 0;
	// The rounded figure decides the unit, so 999.6 MB reads "1 GB".
	while (Number(value.toPrecision(3)) >= 1000 && unit < UNITS.length - 1) {
		value /= 1000;
		unit += 1;
	}
	return new Intl.NumberFormat(getLocale(), {
		style: 'unit',
		unit: UNITS[unit],
		unitDisplay: 'short',
		maximumSignificantDigits: 3
	}).format(value);
}
