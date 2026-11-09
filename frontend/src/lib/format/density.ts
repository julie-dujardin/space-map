/** A density against the nearest of a few materials a reader knows. */

import * as m from '$lib/paraglide/messages.js';
import { ltrIsolate } from './bidi';
import { earthRatio, earthRatioParts, type RatioWords } from './quantities';

interface Rung {
	gcm3: number;
	words: RatioWords;
}

/**
 * Materials a reader can picture, in g/cm³. Tungsten tops the solids, not
 * osmium, because people can hold tungsten. Air is ISA sea level; rock is
 * Earth's crust.
 */
export const DENSITY_LADDER: readonly Rung[] = [
	{ gcm3: 0.001225, words: { times: m.density_times_air, percent: m.density_percent_air } },
	{ gcm3: 1, words: { times: m.density_times_water, percent: m.density_percent_water } },
	{ gcm3: 2.7, words: { times: m.density_times_rock, percent: m.density_percent_rock } },
	{ gcm3: 7.874, words: { times: m.density_times_iron, percent: m.density_percent_iron } },
	{
		gcm3: 19.25,
		words: { times: m.density_times_tungsten, percent: m.density_percent_tungsten }
	},
	{ gcm3: 2.3e14, words: { times: m.density_times_nucleus, percent: m.density_percent_nucleus } }
];

/** The rung nearest `gcm3` in log space. */
export function nearestRung(gcm3: number): Rung {
	const distance = (rung: Rung) => Math.abs(Math.log(gcm3 / rung.gcm3));
	return DENSITY_LADDER.reduce((best, rung) => (distance(rung) < distance(best) ? rung : best));
}

/**
 * "1.41× water", "69% of water", "140,000× tungsten". A span compares both ends
 * with the rung of their geometric mean, as one figure where they round
 * alike. Undefined on a rung, and for a span across one.
 */
export function densityComparison(gcm3: number | readonly [number, number]): string | undefined {
	if (typeof gcm3 === 'number') {
		const rung = nearestRung(gcm3);
		return earthRatio(gcm3 / rung.gcm3, { words: rung.words }) ?? undefined;
	}
	const [low, high] = gcm3;
	const rung = nearestRung(Math.sqrt(low * high));
	const ends = [low, high].map((end) => earthRatioParts(end / rung.gcm3));
	const [a, b] = ends;
	if (!a || !b) return undefined;
	if ('multiple' in a && 'multiple' in b) {
		return rung.words.times({ value: span(a.multiple, b.multiple) });
	}
	if ('percent' in a && 'percent' in b) {
		return rung.words.percent({ value: span(a.percent, b.percent) });
	}
	return undefined;
}

function span(low: string, high: string): string {
	return low === high ? low : ltrIsolate(`${low}–${high}`);
}
