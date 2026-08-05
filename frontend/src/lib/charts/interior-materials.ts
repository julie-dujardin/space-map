/**
 * Presentation rules for the interior composition bars: which colour a
 * material or a layer-detail species gets, and how each is named.
 *
 * Colour follows the material, not its rank, so silicate reads the same ochre
 * on Mercury and on Pluto. Nine materials, but only two groups ever share a
 * bar — rock-and-ice bodies draw from {silicate, metal, water, sulfide,
 * organic, volatile}, giants and stars from {hydrogen, helium,
 * heavy_elements} — so those are the sets the palette was separated across.
 * The pipeline drops anything under 0.5% of the body, so there is no trace
 * bucket here: what arrives is already the list worth drawing.
 */

import * as m from '$lib/paraglide/messages.js';
import { formatFormula } from '$lib/charts/atmosphere-species';
import type { CompositionSegment } from '$lib/charts/composition-bar';
import { formatPercent } from '$lib/format/quantities';

/** Every material the pipeline can emit; see `constants/interior/schema.py`. */
const KNOWN_MATERIALS = new Set([
	'metal',
	'sulfide',
	'silicate',
	'water',
	'volatile',
	'organic',
	'hydrogen',
	'helium',
	'heavy_elements'
]);

const MATERIAL_NAME: Record<string, () => string> = {
	metal: m.material_metal,
	sulfide: m.material_sulfide,
	silicate: m.material_silicate,
	water: m.material_water,
	volatile: m.material_volatile,
	organic: m.material_organic,
	hydrogen: m.material_hydrogen,
	helium: m.material_helium,
	heavy_elements: m.material_heavy_elements
};

/**
 * Where a material is a single element, the legend wears its symbol, matching
 * the atmosphere chart directly above it on a giant — that bar is formula-first
 * and spells the species out on hover. Everything else is a class of stuff
 * rather than an element ("rock", "heavier elements") and has no symbol to
 * wear, so it keeps its name in both places. Symbols are not localized, for
 * the same reason the atmosphere's formulas are not.
 */
const MATERIAL_SYMBOL: Record<string, string> = {
	hydrogen: 'H',
	helium: 'He'
};

export interface MaterialShare {
	material: string;
	/** Fraction of the body by mass, 0–1. */
	share: number;
}

interface MaterialSegment {
	material: string;
	/** What the bar and legend show. */
	symbol: string;
	/** What the hover shows — the symbol spelled out. */
	name: string;
	share: number;
	color: string;
}

/** Rank materials and assign colours. Input order is ignored — the bar always
 *  reads most to least abundant. */
function compositionSegments(composition: MaterialShare[]): MaterialSegment[] {
	return [...composition]
		.sort((a, b) => b.share - a.share)
		.map((c) => ({
			material: c.material,
			symbol: MATERIAL_SYMBOL[c.material] ?? materialName(c.material),
			name: materialName(c.material),
			share: c.share,
			color: materialColor(c.material)
		}));
}

/**
 * The bar-ready segments, shared by the Interior panel and the layer cards so a
 * share of rock reads and hovers identically in both. The bar always hovers —
 * a coloured block says nothing on its own — but the legend only hovers where
 * its label is a symbol: "H" needs spelling out, "rock" does not.
 */
export function materialSegments(composition: MaterialShare[]): CompositionSegment[] {
	return compositionSegments(composition).map((segment) => ({
		key: segment.material,
		label: segment.symbol,
		value: formatPercent(segment.share),
		tooltip: m.interior_material_value({
			name: segment.name,
			value: formatPercent(segment.share)
		}),
		labelIsAbbreviated: segment.symbol !== segment.name,
		share: segment.share,
		color: segment.color
	}));
}

/** Localized material name, e.g. "silicate" → "rock". Falls back to the key
 *  for a material with no message yet. */
export function materialName(material: string): string {
	const fn = MATERIAL_NAME[material];
	if (!fn) {
		console.warn(`Missing material name: ${material}`);
		return material;
	}
	return fn();
}

/** A material with no colour of its own would draw as nothing at all. */
function materialColor(material: string): string {
	if (!KNOWN_MATERIALS.has(material)) {
		console.warn(`Missing material colour: ${material}`);
		return 'var(--muted-foreground)';
	}
	return `var(--material-${material.replace('_', '-')})`;
}

/**
 * Every species a layer `Detail` can list; see `constants/interior/bodies.py`.
 * Each has a `--species-<formula>` in app.css, seeded from what the substance
 * looks like the way the gas palette is; Fe and Si alias their `--gas-*`
 * colours, so the element reads the same in a core as in an exosphere.
 */
const KNOWN_SPECIES = new Set([
	'SiO2',
	'Al2O3',
	'FeO',
	'MgO',
	'CaO',
	'Na2O',
	'K2O',
	'TiO2',
	'Fe',
	'Ni',
	'Co',
	'S',
	'Si',
	'Fe-Ni'
]);

/** Localized species name for the hover label, e.g. "SiO2" → "silicon
 *  dioxide". Falls back to the formula for a species with no message yet. */
export function detailSpeciesName(species: string): string {
	const key = `species_name_${species.toLowerCase().replace('-', '_')}`;
	const fn = (m as unknown as Record<string, (() => string) | undefined>)[key];
	if (!fn) {
		console.warn(`Missing species name: ${key}`);
		return formatFormula(species);
	}
	return fn();
}

/** A species with no colour of its own would draw as nothing at all. */
export function detailSpeciesColor(species: string): string {
	if (!KNOWN_SPECIES.has(species)) {
		console.warn(`Missing species colour: ${species}`);
		return 'var(--muted-foreground)';
	}
	return `var(--species-${species.toLowerCase()})`;
}
