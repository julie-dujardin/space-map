import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: () => 'en-US' }));

import { formatCurrency, formatNumber, scientificNotation, ucfirst } from './quantities';

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

describe('formatCurrency', () => {
	it('formats EUR', () => {
		const result = formatCurrency({ value: 42000000, currency: 'EUR' });
		expect(result).toContain('42,000,000');
		expect(result).toContain('€');
	});

	it('formats USD', () => {
		const result = formatCurrency({ value: 1500, currency: 'USD' });
		expect(result).toContain('1,500');
		expect(result).toContain('$');
	});
});

describe('scientificNotation', () => {
	it.each([
		{ n: 1.7e-6, digits: 2, expected: '1.7×10⁻⁶' },
		{ n: 2.66e10, digits: 2, expected: '2.7×10¹⁰' },
		{ n: 5e-10, digits: 2, expected: '5×10⁻¹⁰' }
	])('scientificNotation($n, $digits) → "$expected"', ({ n, digits, expected }) => {
		expect(scientificNotation(n, digits)).toBe(expected);
	});

	// A mantissa that rounds up to 10 belongs in the next decade: Pluto's ocean
	// printed "10×10⁸ km³" beside Earth's "1.3×10⁹".
	it.each([
		{ n: 9.96e8, digits: 2, expected: '1×10⁹' },
		{ n: 9.999e-4, digits: 2, expected: '1×10⁻³' },
		{ n: 9.9996e5, digits: 3, expected: '1×10⁶' }
	])('carries the rounded mantissa: $n → "$expected"', ({ n, digits, expected }) => {
		expect(scientificNotation(n, digits)).toBe(expected);
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
