import { describe, expect, it } from 'vitest';
import {
	EARTH_IRRADIANCE_W_M2,
	formatLuminosity,
	irradianceUnit,
	luminosityComparison,
	SOLAR_LUMINOSITY_W
} from './light';

/** The text without its bidi isolates and with plain spaces. */
const ISOLATES = new RegExp('[\\u2066-\\u2069]', 'g');
const NO_BREAK = new RegExp('\\u00a0', 'g');
const plain = (value: string | undefined) => value?.replace(ISOLATES, '').replace(NO_BREAK, ' ');

describe('a luminosity', () => {
	it('reads in watts on its power of ten, against the Sun', () => {
		expect(formatLuminosity(SOLAR_LUMINOSITY_W)).toBe('3.83×10²⁶ W');
		expect(luminosityComparison(SOLAR_LUMINOSITY_W)).toBeUndefined();
		expect(plain(luminosityComparison(0.00152 * SOLAR_LUMINOSITY_W))).toBe("0.15% of the Sun's");
		expect(
			plain(
				luminosityComparison(
					25.4 * SOLAR_LUMINOSITY_W,
					0.4 * SOLAR_LUMINOSITY_W,
					0.4 * SOLAR_LUMINOSITY_W
				)
			)
		).toBe('(25.40 ± 0.40)× the Sun');
	});
});

describe('an irradiance', () => {
	it.each([
		[0.641, 'W/m²', 1],
		[2.1, 'kW/m²', 1e3],
		[2400, 'MW/m²', 1e6]
	])("takes the unit of %f times Earth's", (earths, unit, wm2) => {
		expect(irradianceUnit(earths * EARTH_IRRADIANCE_W_M2)).toEqual({ unit, wm2 });
	});
});
