import { describe, it, expect } from 'vitest';
import { formatTripTime } from './format';

/** Days per month the formatter rounds against. */
const MONTH = 30.44;

describe('formatTripTime', () => {
	it('gives bare days under a month', () => {
		expect(formatTripTime(0)).toBe('0 d');
		expect(formatTripTime(17)).toBe('17 d');
	});

	it('gives months and days up to a year', () => {
		expect(formatTripTime(MONTH * 6 + 20)).toBe('6 mo 20 d');
		expect(formatTripTime(MONTH * 3)).toBe('3 mo');
	});

	// Rounding the remainder can reach a full month; "3 mo 30 d" is not a
	// duration anyone writes.
	it('carries a rounded remainder into the next month', () => {
		expect(formatTripTime(MONTH * 3 + 30.2)).toBe('4 mo');
	});

	it('switches to years past twelve months', () => {
		expect(formatTripTime(MONTH * 12)).toBe('1 y');
		expect(formatTripTime(MONTH * 17 + 17)).toBe('1 y 5 mo');
		expect(formatTripTime(MONTH * 45 + 25)).toBe('3 y 9 mo');
	});

	// The same carry, one unit up: eleven months and a rounded-up remainder is a
	// year, not "12 mo".
	it('carries a full twelfth month into a year', () => {
		expect(formatTripTime(MONTH * 11 + 30.2)).toBe('1 y');
	});

	it('refuses to render a nonsense duration', () => {
		expect(formatTripTime(NaN)).toBe('—');
		expect(formatTripTime(-1)).toBe('—');
	});
});
