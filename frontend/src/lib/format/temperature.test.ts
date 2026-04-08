import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: () => 'en-US' }));

import { convertTemperature } from './temperature';

describe('convertTemperature', () => {
	it.each([
		{ value: 49, expected: -224 },
		{ value: 53, expected: -220 },
		{ value: 57, expected: -216 },
		{ value: 5800, expected: 5500 },
		{ value: 288, expected: 15 },
		{ value: 0, expected: -273 }
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
