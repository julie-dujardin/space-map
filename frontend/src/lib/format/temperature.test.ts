import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: () => 'en-US' }));

import { convertTemperature } from './temperature';

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
