import { describe, expect, it } from 'vitest';
import { joinParts } from '$lib/format/quantities';
import { formatRingMass } from './stats';

describe('a ring system mass', () => {
	it('reads in kilograms and a power of ten, with its published ±', () => {
		const mass = formatRingMass({ low_kg: 1.54e19, uncertainty_kg: 0.49e19 });
		expect(joinParts(mass)).toBe('1.54×10¹⁹ kg');
		expect(mass.note).toBe('± 0.49×10¹⁹ kg');
	});

	it('writes a range on the power of ten of its upper end', () => {
		expect(joinParts(formatRingMass({ low_kg: 4e15, high_kg: 1.2e16 }))).toBe('0.4–1.2×10¹⁶ kg');
	});

	it('keeps a bound and a rounded figure as hedges', () => {
		expect(joinParts(formatRingMass({ low_kg: 1e16, upper_limit: true }))).toBe('< 1×10¹⁶ kg');
		expect(joinParts(formatRingMass({ low_kg: 3e17, approximate: true }))).toBe('≈ 3×10¹⁷ kg');
	});
});
