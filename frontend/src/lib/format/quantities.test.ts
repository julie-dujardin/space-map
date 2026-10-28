import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: () => 'en-US' }));

import {
	formatCompactCurrency,
	formatCatalogueQuantity,
	formatCurrency,
	formatMeasuredQuantity,
	formatNumber,
	formatPercent,
	formatQuantity,
	percentParts,
	scientificNotation,
	spanFields,
	ucfirst
} from './quantities';

const plain = (value: string) => value.replace(/[\u2066-\u2069]/g, '').replace(/\u00a0/g, ' ');

describe('formatMeasuredQuantity', () => {
	it('uses the normal quantity path without uncertainty', () => {
		const measured = formatMeasuredQuantity({ value: 0.693, unit: 'R⊕' });
		expect(measured).toBe(formatQuantity({ value: 0.693, unit: 'R⊕' }, true));
	});

	it('formats symmetric and asymmetric uncertainty', () => {
		expect(
			plain(
				formatMeasuredQuantity({
					value: 1.055,
					upperError: 0.055,
					lowerError: 0.055,
					unit: 'M⊕'
				})
			)
		).toBe('1.055 ± 0.055 M⊕');
		expect(
			plain(
				formatMeasuredQuantity({
					value: 3.3,
					upperError: 1.8,
					lowerError: 2.3,
					unit: '°',
					tight: true
				})
			)
		).toBe('3.3° (1.0–5.1°)');
	});

	it('keeps a catalogue value at its published precision', () => {
		expect(plain(formatCatalogueQuantity(1.4, null, null, 'M☉'))).toBe('1.4 M☉');
	});

	it('rounds converted uncertainty at its significant place', () => {
		expect(
			plain(
				formatMeasuredQuantity({
					value: 626_130,
					upperError: 13_914,
					lowerError: 13_914,
					unit: 'km',
					roundLargeErrors: true
				})
			)
		).toBe('626,000 ± 14,000 km');
	});

	it('writes the figures on one power of ten', () => {
		const kg = (upperError: number | null, lowerError: number | null) =>
			plain(
				formatMeasuredQuantity({ value: 8.206e24, upperError, lowerError, unit: 'kg', power: 24 })
			);
		expect(kg(null, null)).toBe('8.206×10²⁴ kg');
		expect(kg(4.1e23, 4.1e23)).toBe('(8.21 ± 0.41)×10²⁴ kg');
		expect(kg(4.1e23, 2e23)).toBe('8.21×10²⁴ kg (8.01–8.62×10²⁴ kg)');
	});
});

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

describe('formatCompactCurrency', () => {
	it.each([
		{ value: 178_000_000, expected: '$178M' },
		{ value: 2_200_000_000, expected: '$2.2B' }
	])('formatCompactCurrency($value) → "$expected"', ({ value, expected }) => {
		expect(formatCompactCurrency({ value, currency: 'USD' })).toBe(expected);
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

describe('percentParts', () => {
	it('splits the sign off the digits', () => {
		expect(percentParts(0.24)).toEqual({ value: '24', unit: '%', tight: true });
	});

	it('joins back to what Intl wrote', () => {
		expect(formatPercent(0.2437, 3)).toBe('24.4%');
	});
});

describe('spanFields', () => {
	it('says a shared sign once', () => {
		// A layer's published mass share, in the sentence that brackets it: the
		// two ends used to be formatted apart and came out "24%–57%".
		expect(spanFields(percentParts(0.24), percentParts(0.57))).toEqual({
			low: '24',
			high: '57%'
		});
	});

	it('says both units where they differ', () => {
		expect(spanFields({ value: '250', unit: 'Ma' }, { value: '1', unit: 'Ga' })).toEqual({
			low: '250 Ma',
			high: '1 Ga'
		});
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
