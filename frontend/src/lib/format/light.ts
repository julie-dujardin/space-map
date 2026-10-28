import * as m from '$lib/paraglide/messages.js';
import { earthRatio, joinParts, scientificParts, type Parts } from './quantities';

/** IAU nominal solar luminosity (2015 Resolution B3). */
export const SOLAR_LUMINOSITY_W = 3.828e26;
/** IAU nominal total solar irradiance at 1 AU (2015 Resolution B3): the
 *  catalogues' unit of a planet's insolation. */
export const EARTH_IRRADIANCE_W_M2 = 1361;

const SUN_WORDS = { times: m.sun_times, percent: m.sun_percent };

/** A star's power on the power of ten of its value, as masses read: red
 *  dwarfs and supergiants are twelve of them apart. */
export function luminosityParts(watts: number): Parts {
	return scientificParts(watts, m.symbol_watt());
}

export function formatLuminosity(watts: number): string {
	return joinParts(luminosityParts(watts));
}

/** What a luminosity comes to against the Sun's, with its errors. */
export function luminosityComparison(
	watts: number,
	upperError: number | null = null,
	lowerError: number | null = null
): string | undefined {
	const ratio = (w: number | null) => w && w / SOLAR_LUMINOSITY_W;
	return (
		earthRatio(watts / SOLAR_LUMINOSITY_W, {
			words: SUN_WORDS,
			upperError: ratio(upperError),
			lowerError: ratio(lowerError)
		}) ?? undefined
	);
}

/** Starlight per square metre, from a cold planet's few W/m² to a hot
 *  Jupiter's MW/m²: the symbol, and the W/m² in one of it. */
export function irradianceUnit(wm2: number): { unit: string; wm2: number } {
	if (wm2 >= 1e6) return { unit: m.symbol_megawatt_per_square_metre(), wm2: 1e6 };
	if (wm2 >= 1e3) return { unit: m.symbol_kilowatt_per_square_metre(), wm2: 1e3 };
	return { unit: m.symbol_watt_per_square_metre(), wm2: 1 };
}
