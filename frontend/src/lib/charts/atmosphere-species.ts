/**
 * Presentation rules for the atmosphere composition bar: which colour a gas
 * gets, how its formula is typeset, and where the bar stops resolving species
 * and starts calling them trace.
 *
 * Colour follows the species, not its rank in the bar, so H₂ reads the same
 * blue on Jupiter and on Saturn.
 */

import * as m from '$lib/paraglide/messages.js';

/** Species below this share are summed into the neutral trace segment. */
const TRACE_SHARE = 0.005;

/** Segments never outnumber the palette; the tail folds into trace. */
const MAX_SEGMENTS = 6;

const SLOT_COUNT = 8;

/**
 * Every gas that can reach a bar segment, coloured explicitly. Slots repeat
 * across the table — eight hues cannot separate twenty gases — but never
 * between two gases that share a body, so no bar draws one hue twice. The
 * grouping follows chemistry where it can: argon's isotopes take argon's
 * neighbourhood, sulphur dioxide the sulphurous amber.
 */
const SPECIES_SLOT: Record<string, number> = {
	H2: 1,
	H: 1,
	Ar: 1,
	He: 2,
	'He-4': 2,
	NH3: 2,
	SO: 2,
	N2: 3,
	'Ne-20': 3,
	O: 3,
	CO2: 4,
	SO2: 4,
	'Ar-40': 4,
	Mg: 4,
	O2: 5,
	'Ne-22': 5,
	CH4: 6,
	'Ar-36': 6,
	H2O: 7,
	Na: 8
};

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

	// The table is built so co-occurring gases never share a hue, but a data
	// change could pair two that do — and a gas outside it has none at all.
	// Both fall back to a leftover hue, biggest segment keeping the canonical
	// one, so a bar never draws the same colour twice whatever it is handed.
	const taken = new Set<number>();
	const segments: BarSegment[] = shown.map((s) => {
		let slot = SPECIES_SLOT[s.formula];
		if (slot === undefined || taken.has(slot)) slot = firstFree(taken) ?? SLOT_COUNT;
		taken.add(slot);
		return {
			key: s.formula,
			formula: formatFormula(s.formula),
			share: s.share,
			color: `var(--gas-${slot})`,
			limit: s.limit === true
		};
	});

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

function firstFree(taken: Set<number>): number | undefined {
	for (let slot = 1; slot <= SLOT_COUNT; slot++) if (!taken.has(slot)) return slot;
	return undefined;
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
