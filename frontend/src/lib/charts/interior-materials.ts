/**
 * The interior's two vocabularies for the composition bar: which colour a
 * material or a layer-detail species gets, and how each is named.
 *
 * Colour follows the material, not its rank, so silicate reads the same ochre
 * on Mercury and on Pluto. Nine materials, but only two groups ever share a
 * bar — rock-and-ice bodies draw from {silicate, metal, water, sulfide,
 * organic, volatile}, giants and stars from {hydrogen, helium,
 * heavy_elements} — so those are the sets the palette was separated across.
 */

import * as m from '$lib/paraglide/messages.js';
import { formatFormula } from '$lib/charts/atmosphere-species';
import type { CompositionEntry } from '$lib/charts/composition-bar';

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
	/** The width the source published around it, on a layer's split. */
	share_range?: [number, number];
}

/**
 * The coarse split, shared by the Interior panel and the layer cards so a share
 * of rock reads and hovers identically in both.
 */
export function materialEntries(composition: MaterialShare[]): CompositionEntry[] {
	return composition.map((c) => ({
		key: c.material,
		label: MATERIAL_SYMBOL[c.material] ?? materialName(c.material),
		name: materialName(c.material),
		share: c.share,
		color: materialColor(c.material),
		range: c.share_range
	}));
}

/** A layer's chemistry, where the literature gives one. Follows the
 *  atmosphere's convention: formula on the bar, the substance on hover. */
export function detailEntries(
	entries: { species: string; fraction: number }[]
): CompositionEntry[] {
	return entries.map((e) => ({
		key: e.species,
		label: formatFormula(e.species),
		name: detailSpeciesName(e.species),
		share: e.fraction,
		color: detailSpeciesColor(e.species)
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
	'Fe-Ni',
	'O',
	'C',
	'H',
	// Seawater, and the salt in it.
	'H2O',
	'Cl',
	'Na',
	'SO4',
	'Mg',
	'Ca',
	'K',
	// Titan's seas.
	'CH4',
	'N2',
	'C2H6'
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
