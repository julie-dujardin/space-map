/**
 * Presentation rules for the interior composition bar: which colour a material
 * gets and how it is named.
 *
 * Colour follows the material, not its rank, so silicate reads the same ochre
 * on Mercury and on Pluto. Nine materials, but only two groups ever share a
 * bar — rock-and-ice bodies draw from {silicate, metal, water, sulfide,
 * organic, volatile_ice}, giants and stars from {hydrogen, helium,
 * heavy_elements} — so those are the sets the palette was separated across.
 * The pipeline drops anything under 0.5% of the body, so there is no trace
 * bucket here: what arrives is already the list worth drawing.
 */

import * as m from '$lib/paraglide/messages.js';

/** Every material the pipeline can emit; see `constants/interior/schema.py`. */
const KNOWN_MATERIALS = new Set([
	'metal',
	'sulfide',
	'silicate',
	'water',
	'volatile_ice',
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
	volatile_ice: m.material_volatile_ice,
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

export interface MaterialSegment {
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
export function compositionSegments(composition: MaterialShare[]): MaterialSegment[] {
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
