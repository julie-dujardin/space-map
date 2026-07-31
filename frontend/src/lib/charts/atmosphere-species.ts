/**
 * Presentation rules for the atmosphere composition bar: which colour a gas
 * gets, how its formula is typeset, and where the bar stops resolving species
 * and starts calling them trace.
 *
 * Colour follows the species, not its rank in the bar, so H₂ reads the same
 * violet on Jupiter and on Saturn.
 */

import * as m from '$lib/paraglide/messages.js';

/** Species below this share are summed into the neutral trace segment. */
const TRACE_SHARE = 0.005;

/** Segments never outnumber the palette; the tail folds into trace. */
const MAX_SEGMENTS = 6;

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

export interface BarSegment {
	key: string;
	/** Typeset formula, or null for the trace bucket (which gets a label). */
	formula: string | null;
	share: number;
	color: string;
	/** Hatched and labelled "<": an upper limit, not an abundance. */
	limit: boolean;
}

/**
 * Rank species, fold the tail into trace, and assign colours. Input order is
 * ignored — the bar always reads most to least abundant.
 */
export function compositionSegments(species: SpeciesShare[]): BarSegment[] {
	const ranked = [...species].sort((a, b) => b.share - a.share);
	const shown = ranked.filter((s) => s.share >= TRACE_SHARE).slice(0, MAX_SEGMENTS);

	const segments: BarSegment[] = shown.map((s) => ({
		key: s.formula,
		formula: formatFormula(s.formula),
		share: s.share,
		color: gasColor(s.formula),
		limit: s.limit === true
	}));

	const trace =
		ranked.reduce((sum, s) => sum + s.share, 0) - shown.reduce((s, x) => s + x.share, 0);
	if (trace >= 0.001)
		segments.push({
			key: '__trace__',
			formula: null,
			share: trace,
			color: 'var(--gas-trace)',
			limit: false
		});
	return segments;
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
