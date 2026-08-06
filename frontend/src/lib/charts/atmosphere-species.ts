/**
 * The atmosphere's vocabulary for the composition bar: which colour a gas gets,
 * how its formula is typeset, and what it is called when spelled out. Ranking
 * and the trace bucket belong to the bar, which draws every composition in the
 * panel the same way.
 *
 * Colour follows the species, not its rank in the bar, so H₂ reads the same
 * violet on Jupiter and on Saturn.
 */

import * as m from '$lib/paraglide/messages.js';
import type { CompositionEntry } from '$lib/charts/composition-bar';

/**
 * Every gas the composition data can name. Each has its own `--gas-<formula>`
 * in app.css; the list exists so a species the palette has never seen warns
 * rather than drawing a segment with no colour.
 */
const KNOWN_GASES = new Set([
	'Ar',
	'Ar-36',
	'Ar-40',
	'C',
	'C2H2',
	'C2H4',
	'C2H6',
	'CH4',
	'CO',
	'CO2',
	'Ca',
	'Fe',
	'H',
	'H2',
	'H2O',
	'HD',
	'HDO',
	'He',
	'He-4',
	'K',
	'Kr',
	'Mg',
	'N',
	'N2',
	'NH3',
	'NO',
	'Na',
	'Ne',
	'Ne-20',
	'Ne-22',
	'O',
	'O2',
	'SO',
	'SO2',
	'Si',
	'Xe'
]);

export interface SpeciesShare {
	formula: string;
	/** Fraction of the listed species, 0–1, in whatever unit the body reports. */
	share: number;
	/** Measurement is a non-detection limit, not an abundance. */
	limit?: boolean;
}

/** Formula on the bar, the gas spelled out on hover. */
export function speciesEntries(species: SpeciesShare[]): CompositionEntry[] {
	return species.map((s) => ({
		key: s.formula,
		label: formatFormula(s.formula),
		name: speciesName(s.formula),
		share: s.share,
		color: gasColor(s.formula),
		limit: s.limit === true
	}));
}

/** Localized gas name for the hover label, e.g. "SO2" → "sulphur dioxide".
 *  Falls back to the formula for a species with no message yet. */
export function speciesName(formula: string): string {
	const key = `gas_name_${formula.toLowerCase().replace('-', '_')}`;
	const fn = (m as unknown as Record<string, (() => string) | undefined>)[key];
	if (!fn) {
		console.warn(`Missing gas name: ${key}`);
		return formatFormula(formula);
	}
	return fn();
}

/** A gas with no colour of its own would draw as nothing at all. */
function gasColor(formula: string): string {
	if (!KNOWN_GASES.has(formula)) {
		console.warn(`Missing gas colour: ${formula}`);
		return 'var(--muted-foreground)';
	}
	return `var(--gas-${formula.toLowerCase()})`;
}

const SUBSCRIPTS = '₀₁₂₃₄₅₆₇₈₉';
const SUPERSCRIPTS = '⁰¹²³⁴⁵⁶⁷⁸⁹';

/**
 * "CO2" → "CO₂", "He-4" → "⁴He". Isotopes lead with the mass number, the
 * convention every source these numbers come from uses.
 */
export function formatFormula(formula: string): string {
	const isotope = /^([A-Za-z]+)-(\d+)$/.exec(formula);
	if (isotope) return [...isotope[2]].map((d) => SUPERSCRIPTS[Number(d)]).join('') + isotope[1];
	return formula.replace(/\d/g, (d) => SUBSCRIPTS[Number(d)]);
}
