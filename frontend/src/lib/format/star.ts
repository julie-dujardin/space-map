/**
 * Catalogue values as a star's panel shows them: each at the precision its
 * uncertainty allows, with the uncertainty beside it. A symmetric error reads
 * "379.2 ± 1.6 mas"; a pair of percentiles reads as a span in parentheses,
 * the way the other panels write a published width.
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { ltrIsolate } from './bidi';
import {
	errorDecimals,
	fixed,
	formatMeasuredQuantity,
	formatValueSpan,
	joinParts,
	powerUnit
} from './quantities';

/** `text` and its error, "06ʰ 45ᵐ 09.25ˢ ± 1.2 mas", as one LTR run. With no
 *  error, `text` alone. */
export function withError(text: string, error: number | null, unit = ''): string {
	if (error === null || !(error > 0)) return text;
	return ltrIsolate(
		`${text} ±\u00a0${joinParts({ value: fixed(error, errorDecimals(error)), unit })}`
	);
}

/** "379.2 ± 1.6 mas". With no error, "0.489 mas" at `decimals` digits, in the
 *  order the other panels give a value and its unit. */
export function plusMinus(value: number, error: number | null, unit = '', decimals = 2): string {
	return formatMeasuredQuantity({
		value,
		upperError: error,
		lowerError: error,
		unit,
		fixedDecimals: decimals
	});
}

/** The errors a pair of bounds gives a value between them. Null for a value on
 *  a bound or past it, which has no error on that side to mirror. */
export function boundErrors(
	value: number,
	low: number | null,
	high: number | null
): { upperError: number; lowerError: number } | null {
	return low !== null && high !== null && low < value && value < high
		? { upperError: high - value, lowerError: value - low }
		: null;
}

/** "2.637 pc (2.626–2.648 pc)": a value and the bounds of its uncertainty, or
 *  "1.30197 ± 0.00008 pc" where they are as good as symmetric. `roundLarge`
 *  as for `errorDecimals`; `power` as for `formatMeasuredQuantity`. */
export function withBounds(
	value: number,
	low: number | null,
	high: number | null,
	unit = '',
	roundLarge = false,
	power?: number
): string {
	if (low === null || high === null || !(high > low)) {
		return formatMeasuredQuantity({ value, unit, fixedDecimals: 2, power });
	}
	const errors = boundErrors(value, low, high);
	if (errors) {
		return formatMeasuredQuantity({ value, ...errors, unit, roundLargeErrors: roundLarge, power });
	}
	const scale = 10 ** -(power ?? 0);
	return formatValueSpan(
		value * scale,
		low * scale,
		high * scale,
		errorDecimals(((high - low) * scale) / 2, roundLarge),
		power === undefined ? { unit } : powerUnit(unit, power)
	);
}

/** Split `total` units of the last digit into whole parts and a remainder, so
 *  a rounding carry runs up: 59.996 s at two digits is the next minute. */
function sexagesimal(value: number, decimals: number): [number, number, number] {
	const step = 10 ** decimals;
	const total = Math.round(value * 3600 * step);
	const unitsPerMinute = 60 * step;
	const whole = Math.floor(total / (60 * unitsPerMinute));
	const minutes = Math.floor((total % (60 * unitsPerMinute)) / unitsPerMinute);
	const seconds = (total % unitsPerMinute) / step;
	return [whole, minutes, seconds];
}

function pad(n: number, digits: number, decimals = 0): string {
	return new Intl.NumberFormat(getLocale(), {
		minimumIntegerDigits: digits,
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals,
		useGrouping: false
	}).format(n);
}

/** Right ascension in hours, minutes and seconds of time, to the precision
 *  of its error (mas on ra·cos dec). */
export function formatRightAscension(
	raDeg: number,
	decDeg: number,
	errorMas: number | null
): string {
	const cosDec = Math.max(Math.cos((decDeg * Math.PI) / 180), 1e-6);
	const errorSeconds = errorMas === null ? null : errorMas / 1000 / 15 / cosDec;
	const d = errorSeconds === null ? 2 : Math.min(errorDecimals(errorSeconds), 6);
	const [h, mm, ss] = sexagesimal(raDeg / 15, d);
	return ltrIsolate(`${pad(h % 24, 2)}ʰ ${pad(mm, 2)}ᵐ ${pad(ss, 2, d)}ˢ`);
}

/** Declination in degrees, minutes and seconds of arc, to the precision of
 *  its error (mas). */
export function formatDeclination(decDeg: number, errorMas: number | null): string {
	const errorSeconds = errorMas === null ? null : errorMas / 1000;
	const d = errorSeconds === null ? 1 : Math.min(errorDecimals(errorSeconds), 5);
	const [deg, mm, ss] = sexagesimal(Math.abs(decDeg), d);
	// Signed always, a negative zero included: −0° 30′ is south of the equator.
	const degrees = new Intl.NumberFormat(getLocale(), {
		minimumIntegerDigits: 2,
		signDisplay: 'always'
	}).format(decDeg < 0 ? -deg : deg);
	return ltrIsolate(`${degrees}° ${pad(mm, 2)}′ ${pad(ss, 2, d)}″`);
}
