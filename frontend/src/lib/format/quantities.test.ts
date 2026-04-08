import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: () => 'en-US' }));

import { formatNumber, ucfirst } from './quantities';

describe('formatNumber', () => {
	it.each([
		{ n: 0, expected: '0' },
		{ n: 1.234, expected: '1.23' },
		{ n: 12.34, expected: '12.3' },
		{ n: 123.4, expected: '123' },
		{ n: 1234, expected: '1,234' },
		{ n: -42.7, expected: '-42.7' },
		{ n: 0.00456, expected: '0.005' }
	])('formatNumber($n) → "$expected"', ({ n, expected }) => {
		expect(formatNumber(n)).toBe(expected);
	});

	it('returns "NaN" for NaN', () => {
		expect(formatNumber(NaN)).toBe('NaN');
	});

	it('returns "Infinity" for Infinity', () => {
		expect(formatNumber(Infinity)).toBe('Infinity');
	});
});

describe('ucfirst', () => {
	it.each([
		{ input: 'hello', expected: 'Hello' },
		{ input: '', expected: '' },
		{ input: 'A', expected: 'A' },
		{ input: 'already Capital', expected: 'Already Capital' }
	])('ucfirst("$input") → "$expected"', ({ input, expected }) => {
		expect(ucfirst(input)).toBe(expected);
	});
});
