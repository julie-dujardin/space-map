import { describe, expect, it } from 'vitest';
import {
	EARTH_MASS_KG,
	formatMass,
	JUPITER_MASS_KG,
	massComparison,
	massReading,
	sizeComparison,
	SOLAR_MASS_KG
} from './mass';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (value: string | undefined) => value?.replace(ISOLATES, '').replace(NO_BREAK, ' ');

describe('a mass', () => {
	it('reads in kilograms, whatever unit the export gave it in', () => {
		expect(formatMass(EARTH_MASS_KG)).toBe('5.97×10²⁴ kg');
		const jupiter = massReading({ value: 317.828, unit: 'earth_mass' });
		expect(jupiter.value).toBe('1.90×10²⁷ kg');
		expect(plain(jupiter.tooltip)).toBe('318× Earth');
		expect(massReading({ value: 10.66, unit: 'exagram' }).value).toBe('1.07×10¹⁶ kg');
	});

	it.each([
		['the Sun', SOLAR_MASS_KG, '1,050× Jupiter'],
		['Jupiter', JUPITER_MASS_KG, '318× Earth'],
		['Saturn', 5.683e26, "30% of Jupiter's"],
		['Proxima Centauri', 0.1221 * SOLAR_MASS_KG, "12% of the Sun's"],
		['the Moon', 7.342e22, "1.2% of Earth's"],
		['Earth', EARTH_MASS_KG, undefined],
		['Ceres', 9.39e20, undefined]
	])('compares %s with the largest body it reaches a tenth of', (_, kg, expected) => {
		expect(plain(massComparison(kg))).toBe(expected);
	});

	it('carries its errors into the comparison', () => {
		const e = EARTH_MASS_KG;
		expect(plain(massComparison(1.055 * e, 0.055 * e, 0.055 * e))).toBe('(1.06 ± 0.06)× Earth');
		// At the digits of the rounded figure: "10", not "10.00".
		expect(plain(massComparison(9.996 * e, 0.7 * e, 0.7 * e))).toBe('(10.0 ± 0.7)× Earth');
		expect(plain(massComparison(9.996 * e, 0.02 * e, 0.02 * e))).toBe('10× Earth');
		expect(plain(massComparison(1.37 * e, 0.07 * e, 0.2 * e))).toBe('1.37 (1.17–1.44)× Earth');
	});
});

describe('sizeComparison', () => {
	it('reads a star against the Sun', () => {
		expect(sizeComparison(725 * 695_700)).toContain('725');
		expect(sizeComparison(725 * 695_700)).toContain('the Sun');
	});

	it('takes the next reference down at parity', () => {
		expect(sizeComparison(695_700)).toContain('Jupiter');
	});

	it('gives a small star as a share of the Sun', () => {
		expect(sizeComparison(0.14 * 695_700)).toContain('14%');
	});

	it('reads a white dwarf against Earth', () => {
		expect(sizeComparison(9_000)).toContain('Earth');
	});
});
