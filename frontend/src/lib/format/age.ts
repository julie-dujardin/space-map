/** Times before present: geologists' symbols for a row, words for its tooltip. */

import * as m from '$lib/paraglide/messages.js';
import type { Measurement } from '$lib/fetch/objects/object-data';
import { ltrIsolate } from './bidi';
import { sigFigures, type PartsOf } from './quantities';

type Words = (inputs: { value: string }) => string;

/** A scale of an age: years per unit, the symbol of a stat cell ("53 ka"),
 *  and the words of a tooltip ("53 thousand years ago") and of an upper limit.
 *  The symbols come from the `symbol_*` messages, so a locale can write its own. */
interface Scale {
	years: number;
	symbol: () => string;
	words: Words;
	under: Words;
}

const LADDER: readonly Scale[] = [
	{
		years: 1e9,
		symbol: m.symbol_gigaannum,
		words: m.activity_age_billion_years,
		under: m.age_under_billion_years
	},
	{
		years: 1e6,
		symbol: m.symbol_megaannum,
		words: m.activity_age_million_years,
		under: m.age_under_million_years
	},
	{
		years: 1e3,
		symbol: m.symbol_kiloannum,
		words: m.activity_age_thousand_years,
		under: m.age_under_thousand_years
	}
];

/** The scale of `years` at the three figures that the row shows, so 999.6 Ma
 *  reads 1 Ga; undefined under a thousand years. */
function scaleOf(years: number): Scale | undefined {
	const shown = Number(years.toPrecision(3));
	return LADDER.find((scale) => shown >= scale.years);
}

/** Years before present. */
export const ageParts: PartsOf = (years) => {
	const scale = scaleOf(years);
	if (!scale) return { value: sigFigures(years), unit: m.symbol_annum() };
	return { value: sigFigures(years / scale.years), unit: scale.symbol() };
};

/** "600 (250–1,000) million years ago", "Less than 100 million years ago": a
 *  measurement in years, at the scale of `ageParts`, with its range at the
 *  same scale. */
export function spellAge({ value, range, upper_limit }: Measurement): string {
	const scale = scaleOf(value) ?? LADDER[LADDER.length - 1];
	const figure = (years: number) => sigFigures(years / scale.years);
	if (upper_limit) return scale.under({ value: ltrIsolate(figure(value)) });
	const text = range ? `${figure(value)} (${figure(range[0])}–${figure(range[1])})` : figure(value);
	return scale.words({ value: ltrIsolate(text) });
}

/** "Formed 13.28 (11.93–13.50) billion years ago". `figure` is the age and its
 *  bounds as the row writes them, in Ga. */
export function formedAgo(figure: string): string {
	return m.age_formed({ ago: LADDER[0].words({ value: ltrIsolate(figure) }) });
}
