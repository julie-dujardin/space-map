import { getLocale } from '$lib/paraglide/runtime.js';
import { ltrIsolate } from './bidi';
import {
	formatCompactNumber,
	formatNumber,
	formatQuantity,
	formatUnit,
	joinParts,
	precisionOptions
} from './quantities';

export type TemperatureUnit = 'kelvin' | 'degree_celsius' | 'degree_fahrenheit';

export const PREFERRED_TEMPERATURE_UNIT: TemperatureUnit = 'degree_celsius'; // TODO make this user-configurable

function toKelvin(value: number, from: TemperatureUnit): number {
	switch (from) {
		case 'kelvin':
			return value;
		case 'degree_celsius':
			return value + 273.15;
		case 'degree_fahrenheit':
			return (value - 32) * (5 / 9) + 273.15;
	}
}

function fromKelvin(kelvin: number, to: TemperatureUnit): number {
	switch (to) {
		case 'kelvin':
			return kelvin;
		case 'degree_celsius':
			return kelvin - 273.15;
		case 'degree_fahrenheit':
			return (kelvin - 273.15) * (9 / 5) + 32;
	}
}

/** Digits kept once a value is large enough that a degree is false precision. */
const DISPLAY_SIGFIGS = 4;

/**
 * Rounding step for a converted temperature: significant-figure coarse at the
 * top of the range, never finer than a degree.
 *
 * Derived from the converted magnitude rather than from the source value's
 * trailing zeros. That distinction is the whole point: reading "100 K" as one
 * significant figure means ±50 K, which rendered Mercury's night side as
 * "-200 °C" — the offset to Celsius lands it near zero, where relative
 * precision explodes. Magnitude can't misfire that way, and the floor keeps
 * every planetary reading exact to the degree.
 */
function displayPrecision(value: number): number {
	if (value === 0) return 1;
	const magnitude = Math.floor(Math.log10(Math.abs(value)));
	return Math.max(1, 10 ** (magnitude - DISPLAY_SIGFIGS + 1));
}

/** Convert a temperature quantity to the preferred unit, at display precision. */
export function convertTemperature(
	q: { value: number; unit: string },
	target: TemperatureUnit = PREFERRED_TEMPERATURE_UNIT
): {
	value: number;
	unit: TemperatureUnit;
} {
	const source = q.unit as TemperatureUnit;
	if (source === target) return { value: q.value, unit: target };
	const converted = fromKelvin(toKelvin(q.value, source), target);
	const precision = displayPrecision(converted);
	return { value: Math.round(converted / precision) * precision, unit: target };
}

/**
 * Where a stellar reading stops being digits anyone reads and starts being a
 * width no chart label has. Set at a million so compact notation never reaches
 * for its thousands suffix: "15.5M °C" is clear, "5.5K °C" reads as kelvin.
 */
const COMPACT_ABOVE = 1_000_000;

/** Every temperature on a page comes through here or the range formatter
 *  below, which share the compaction rule: the corona and the core read alike. */
export function formatTemperature(
	q: { value: number; unit: string },
	target?: TemperatureUnit
): string {
	const t = convertTemperature(q, target);
	if (Math.abs(t.value) < COMPACT_ABOVE) return formatQuantity(t, true);
	return joinParts({ value: formatCompactNumber(t.value), unit: formatUnit(t.unit, true) });
}

/**
 * A temperature, or the bracket a model gives instead of one, in the space a
 * chart label has: the unit said once at the end, and the numbers compacted
 * together once either end runs long.
 *
 * `formatRange` rather than two numbers with a dash between them, because a
 * locale that spells its magnitude out only spells it once — Russian gives
 * "15,5–15,7 млн", not "15,5 млн–15,7 млн" — and because the separator itself
 * is a locale's own (an ideographic "～" in Japanese).
 */
export function formatTemperatureRange(
	low: { value: number; unit: string },
	high?: { value: number; unit: string } | null,
	target?: TemperatureUnit
): string {
	const a = convertTemperature(low, target);
	const b = high ? convertTemperature(high, target) : a;
	const peak = Math.max(Math.abs(a.value), Math.abs(b.value));
	const compact = peak >= COMPACT_ABOVE;
	const unit = formatUnit(a.unit, true);
	if (a.value === b.value) {
		return joinParts({
			value: compact ? formatCompactNumber(a.value) : formatNumber(a.value),
			unit
		});
	}
	const format = new Intl.NumberFormat(
		getLocale(),
		compact ? { notation: 'compact', maximumSignificantDigits: 3 } : precisionOptions(peak)
	);
	return joinParts({ value: format.formatRange(a.value, b.value), unit });
}

// Spaced, because an end can be negative and "464 –-28" jams a separator
// against a minus sign.
const SPAN_SEPARATOR = ' – ';

/**
 * The two ends of something that has two ends — a layer, bottom first, against
 * a boundary's single reading.
 *
 * Bottom first rather than lowest first: a troposphere cools with height and
 * the stratosphere above it warms, and a sorted range would report both the
 * same way.
 *
 * Each end is formatted on its own rather than as a range, because a span can
 * cross the point where compact notation takes over and "20K – 1M ℃" would
 * read as 20 kelvin. That is also why this cannot use `formatRange`.
 */
export function formatTemperatureSpan(
	bottom: { value: number; unit: string },
	top: { value: number; unit: string },
	target?: TemperatureUnit
): string {
	const a = convertTemperature(bottom, target);
	const b = convertTemperature(top, target);
	const unit = formatUnit(a.unit, true);
	// An isothermal layer has one temperature, not a span of the same number.
	if (a.value === b.value) return joinParts({ value: oneNumber(a.value), unit });
	return joinParts({ value: `${oneNumber(a.value)}${SPAN_SEPARATOR}${oneNumber(b.value)}`, unit });
}

function oneNumber(value: number): string {
	return Math.abs(value) >= COMPACT_ABOVE ? formatCompactNumber(value) : formatNumber(value);
}

// The charts carry temperatures as bare kelvin numbers; these wrap them for
// display, isolated so the digits survive an RTL sentence.

export function formatKelvin(k: number): string {
	return ltrIsolate(formatTemperature({ value: k, unit: 'kelvin' }));
}

export function formatKelvinRange(lowK: number, highK: number): string {
	return ltrIsolate(
		formatTemperatureRange({ value: lowK, unit: 'kelvin' }, { value: highK, unit: 'kelvin' })
	);
}

export function formatKelvinSpan(bottomK: number, topK: number): string {
	return ltrIsolate(
		formatTemperatureSpan({ value: bottomK, unit: 'kelvin' }, { value: topK, unit: 'kelvin' })
	);
}
