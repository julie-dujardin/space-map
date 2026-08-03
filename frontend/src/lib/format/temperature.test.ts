import { describe, it, expect } from 'vitest';

// No runtime mock: the unit symbols come out of paraglide, and stubbing the
// runtime cuts the messages off from their locale.
import { convertTemperature, formatTemperatureRange } from './temperature';

describe('convertTemperature', () => {
	it.each([
		{ value: 49, expected: -224 },
		{ value: 53, expected: -220 },
		{ value: 57, expected: -216 },
		{ value: 288, expected: 15 },
		{ value: 0, expected: -273 },
		// Round kelvin values must not be read as low-precision: Mercury's night
		// and day sides used to render as -200 and 400 °C.
		{ value: 100, expected: -173 },
		{ value: 700, expected: 427 },
		// Past four significant figures a degree is noise, so the step coarsens:
		// the Sun's photosphere keeps its degree, its corona does not.
		{ value: 5772, expected: 5499 },
		{ value: 2_000_000, expected: 2_000_000 },
		{ value: 15_710_000, expected: 15_710_000 }
	])('$value K → $expected °C', ({ value, expected }) => {
		const result = convertTemperature({ value, unit: 'kelvin' });
		expect(result.unit).toBe('degree_celsius');
		expect(result.value).toBe(expected);
	});

	it('returns input unchanged when source matches target', () => {
		const result = convertTemperature({ value: 20, unit: 'degree_celsius' });
		expect(result).toEqual({ value: 20, unit: 'degree_celsius' });
	});
});

describe('formatTemperatureRange', () => {
	const kelvin = (value: number) => ({ value, unit: 'kelvin' });

	it('says the unit once across a bracket', () => {
		expect(formatTemperatureRange(kelvin(2000), kelvin(2400))).toBe('1,727–2,127 °C');
	});

	it('collapses a bracket whose ends agree', () => {
		expect(formatTemperatureRange(kelvin(288), kelvin(288))).toBe('15 °C');
	});

	it('reads a lone value as a bracket of one', () => {
		expect(formatTemperatureRange(kelvin(288))).toBe('15 °C');
	});

	// The Sun's core is 24 characters written out, which no chart label fits.
	it('compacts a stellar bracket', () => {
		expect(formatTemperatureRange(kelvin(15_500_000), kelvin(15_700_000))).toBe('15.5M – 15.7M °C');
	});

	// A thousands suffix next to a temperature reads as kelvin, so compaction
	// starts above it — Jupiter's core stays in digits.
	it('leaves thousands written out', () => {
		expect(formatTemperatureRange(kelvin(15_000), kelvin(36_000))).toBe('14,730–35,730 °C');
	});
});
