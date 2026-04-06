/** 1 AU = this many Three.js units */
export const AU_SCALE = 10;
/** 1 AU in km */
export const AU_KM = 149_597_870.7;
/** Convert km to scene units */

export function kmToScene(km: number): number {
	return (km / AU_KM) * AU_SCALE;
}

/* ── Temperature conversion ─────────────────────────────────── */

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

function significantDigits(n: number): number {
	if (n === 0) return 1;
	const s = Math.abs(n).toExponential();
	const mantissa = s.slice(0, s.indexOf('e'));
	return mantissa.replace('.', '').replace(/^0+/, '').length;
}

function toSignificantDigits(n: number, digits: number): number {
	if (n === 0) return 0;
	const magnitude = Math.floor(Math.log10(Math.abs(n)));
	const factor = Math.pow(10, digits - 1 - magnitude);
	return Math.round(n * factor) / factor;
}

/** Convert a temperature quantity to the preferred unit, preserving significant digits. */
export function convertTemperature(q: { value: number; unit: string }): {
	value: number;
	unit: TemperatureUnit;
} {
	const target = PREFERRED_TEMPERATURE_UNIT;
	const source = q.unit as TemperatureUnit;
	if (source === target) return { value: q.value, unit: target };
	const converted = fromKelvin(toKelvin(q.value, source), target);
	return { value: toSignificantDigits(converted, significantDigits(q.value)), unit: target };
}
