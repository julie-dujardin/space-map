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

/** Place value of the least significant digit (e.g. 49 → 1, 4900 → 100, 4.9 → 0.1). */
function absolutePrecision(n: number): number {
	if (n === 0) return 1;
	const s = Math.abs(n).toExponential();
	const mantissa = s.slice(0, s.indexOf('e'));
	const sigfigs = mantissa.replace('.', '').replace(/^0+/, '').length;
	const magnitude = Math.floor(Math.log10(Math.abs(n)));
	return Math.pow(10, magnitude - sigfigs + 1);
}

/** Derivative dOutput/dInput for the conversion path, used to scale uncertainty. */
function conversionScale(from: TemperatureUnit, to: TemperatureUnit): number {
	if (from === to) return 1;
	// K↔C is pure offset → derivative = 1
	// Anything involving F has a 9/5 (or 5/9) scaling factor
	const involvesF = from === 'degree_fahrenheit' || to === 'degree_fahrenheit';
	if (!involvesF) return 1;
	return to === 'degree_fahrenheit' ? 9 / 5 : 5 / 9;
}

function roundToPrecision(n: number, precision: number): number {
	return Math.round(n / precision) * precision;
}

/** Convert a temperature quantity to the preferred unit, preserving significant digits. */
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
	const precision = absolutePrecision(q.value) * conversionScale(source, target);
	return { value: roundToPrecision(converted, precision), unit: target };
}

export function formatTemperature(
	q: { value: number; unit: string },
	target?: TemperatureUnit
): string {
	return formatQuantity(convertTemperature(q, target), true);
}

/**
 * Stellar temperatures stay in kelvin: the 273.15 offset to °C is noise beside
 * a million-degree corona, and kelvin is the convention for stars anyway.
 */
export function formatStellarTemperature(q: { value: number; unit: string }): string {
	return formatQuantity(convertTemperature(q, 'kelvin'), true);
}
