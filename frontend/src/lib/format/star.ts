/**
 * Catalogue values as a star's panel shows them: each at the precision its
 * uncertainty allows, with the uncertainty beside it. A symmetric error reads
 * "379.2 ± 1.6 mas"; a pair of percentiles reads as a span in parentheses,
 * the way the other panels write a published width.
 */

import { getLocale } from '$lib/paraglide/runtime.js';
import { ltrIsolate } from './bidi';
import { joinParts } from './quantities';

/** Fraction digits that show `error` to two significant figures. */
export function errorDecimals(error: number): number {
	if (!(error > 0) || !Number.isFinite(error)) return 2;
	// A float32 0.01 is 0.0099999998: its decade is still the hundredths.
	return Math.min(8, Math.max(0, 1 - Math.floor(Math.log10(error) + 1e-6)));
}

/** `value` with exactly `decimals` fraction digits, in the reader's locale. */
export function fixed(value: number, decimals: number): string {
	return new Intl.NumberFormat(getLocale(), {
		minimumFractionDigits: decimals,
		maximumFractionDigits: decimals
	}).format(value);
}

/** Bounds this close to symmetric read as one ± error. */
const SYMMETRIC = 0.1;

/** A figure and its unit, kept on one line. */
function unitOf(text: string, unit: string): string {
	return unit ? `${text}\u00a0${unit}` : text;
}

/** `text` and its error, "06ʰ 45ᵐ 09.25ˢ ± 1.2 mas", as one LTR run that
 *  breaks only before the ±. With no error, `text` alone. */
export function withError(text: string, error: number | null, unit = ''): string {
	if (error === null || !(error > 0)) return text;
	return ltrIsolate(`${text} ±\u00a0${unitOf(fixed(error, errorDecimals(error)), unit)}`);
}

/** "379.2 ± 1.6 mas". With no error, "0.489 mas" at `decimals` digits, in the
 *  order the other panels give a value and its unit. */
export function plusMinus(value: number, error: number | null, unit = '', decimals = 2): string {
	if (error === null || !(error > 0)) return joinParts({ value: fixed(value, decimals), unit });
	return withError(fixed(value, errorDecimals(error)), error, unit);
}

/** "2.637 pc (2.626–2.648 pc)": a value and the bounds of its uncertainty, or
 *  "1.30197 ± 0.00008 pc" where they are as good as symmetric. */
export function withBounds(
	value: number,
	low: number | null,
	high: number | null,
	unit = ''
): string {
	if (low === null || high === null || !(high > low)) {
		return joinParts({ value: fixed(value, 2), unit });
	}
	const half = (high - low) / 2;
	if (Math.abs(high - value - (value - low)) <= SYMMETRIC * half) {
		return plusMinus(value, half, unit);
	}
	const d = errorDecimals(half);
	// Spaced where an end is negative: "−0.18–−0.17" jams the dash against a sign.
	const separator = low < 0 || high < 0 ? ' – ' : '–';
	const span = unitOf(`${fixed(low, d)}${separator}${fixed(high, d)}`, unit);
	return ltrIsolate(`${unitOf(fixed(value, d), unit)} (${span})`);
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
