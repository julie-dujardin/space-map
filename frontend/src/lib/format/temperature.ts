import { formatQuantity } from './quantities';

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

export function formatTemperature(
	q: { value: number; unit: string },
	target?: TemperatureUnit
): string {
	return formatQuantity(convertTemperature(q, target), true);
}
