/**
 * Energy in joules, with the SI prefix that keeps the figure readable, and its
 * TNT equivalent.
 *
 * Each prefixed unit has its own message. The prefix changes with the locale,
 * for example кДж in Russian.
 */

import * as m from '$lib/paraglide/messages.js';
import { ltrIsolate } from './bidi';
import { joinPartsNoBreak, sigFigures, type Parts } from './quantities';

const JOULES: readonly (readonly [number, () => string])[] = [
	[1e18, m.symbol_exajoule],
	[1e15, m.symbol_petajoule],
	[1e12, m.symbol_terajoule],
	[1e9, m.symbol_gigajoule],
	[1e6, m.symbol_megajoule],
	[1e3, m.symbol_kilojoule],
	[1, m.symbol_joule],
	[1e-3, m.symbol_millijoule]
];

/** The largest unit that keeps the figure at 1 or more, to `digits`
 *  significant figures. The rounding comes first, so 999.7 MJ gives 1 GJ. */
export function jouleParts(joules: number, digits = 2): Parts {
	if (!Number.isFinite(joules)) return { value: '—', unit: '' };
	const rounded = Number(joules.toPrecision(digits));
	const [scale, unit] = JOULES.find(([step]) => rounded >= step) ?? JOULES[JOULES.length - 1];
	return { value: sigFigures(rounded / scale, digits), unit: unit() };
}

export function formatJoules(joules: number, digits = 2): string {
	return joinPartsNoBreak(jouleParts(joules, digits));
}

/** Joules in one gram of TNT. It is the convention that sets one tonne of TNT
 *  to 4.184 GJ (NIST SP 811). */
export const JOULES_PER_GRAM_TNT = 4184;

/** Grams of TNT in each unit, largest first. */
const TNT_GRAMS: readonly (readonly [number, () => string])[] = [
	[1e15, m.symbol_gigatonne],
	[1e12, m.symbol_megatonne],
	[1e9, m.symbol_kilotonne],
	[1e6, m.symbol_tonne],
	[1e3, m.symbol_kilogram],
	[1, m.symbol_gram]
];

/** The mass of TNT that releases `joules`, in the largest unit that keeps the
 *  figure at 1 or more. Null below one gram, where a mass of explosive tells
 *  the reader nothing. The rounding comes first, as in `jouleParts`. */
export function tntParts(joules: number, digits = 2): Parts | null {
	if (!Number.isFinite(joules)) return null;
	const grams = Number((joules / JOULES_PER_GRAM_TNT).toPrecision(digits));
	const step = TNT_GRAMS.find(([scale]) => grams >= scale);
	if (!step) return null;
	const [scale, unit] = step;
	return { value: sigFigures(grams / scale, digits), unit: unit() };
}

/**
 * Joules with their TNT equivalent, "830 MJ (200 kg of TNT)", or the joules
 * alone below one gram of TNT. Each measure is in its own isolate. Without
 * them, right-to-left text joins a unit to the figure of the other measure.
 */
export function formatJoulesWithTnt(joules: number, digits = 2): string {
	const energy = ltrIsolate(formatJoules(joules, digits));
	const tnt = tntParts(joules, digits);
	return tnt ? m.energy_tnt_equivalent({ energy, tnt: ltrIsolate(joinPartsNoBreak(tnt)) }) : energy;
}
