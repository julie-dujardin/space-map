import { describe, expect, it } from 'vitest';
import {
	EARTH_MASS_KG,
	formatMass,
	JUPITER_MASS_KG,
	massComparison,
	massReading,
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
		expect(plain(massComparison(1.055 * e, 0.055 * e, 0.055 * e))).toBe('(1.055 ± 0.055)× Earth');
		expect(plain(massComparison(1.37 * e, 0.07 * e, 0.2 * e))).toBe('1.370 (1.170–1.440)× Earth');
	});
});
