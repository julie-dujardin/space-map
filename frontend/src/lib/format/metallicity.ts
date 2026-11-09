/** A metallicity in dex against the Sun's, as a multiple either way. */

import * as m from '$lib/paraglide/messages.js';
import { ltrIsolate } from './bidi';
import { atParity, sigFigures } from './quantities';

/** Two figures: a dex value has two decimals at most. */
const DIGITS = 2;

/** [M/H] measures all heavy elements, [Fe/H] iron alone. */
const WORDS = {
	mh: {
		more: m.metallicity_more_heavy_elements,
		less: m.metallicity_less_heavy_elements,
		solar: m.metallicity_solar_heavy_elements
	},
	feh: {
		more: m.metallicity_more_iron,
		less: m.metallicity_less_iron,
		solar: m.metallicity_solar_iron
	}
};

/** "1.6× more heavy elements than the Sun" at +0.2 dex, "11× less" at −1.05. */
export function metallicityComparison(dex: number, quantity: 'mh' | 'feh'): string {
	const words = WORDS[quantity];
	const ratio = 10 ** Math.abs(dex);
	if (atParity(ratio, DIGITS)) return words.solar();
	const value = ltrIsolate(sigFigures(ratio, DIGITS));
	return dex > 0 ? words.more({ value }) : words.less({ value });
}
