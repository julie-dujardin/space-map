/**
 * How a layer looks in the cross-sections, as opposed to how it reads in a
 * chart.
 *
 * The composition bars keep the categorical palette in `interior-materials.ts`,
 * where the job is telling nine materials apart at a glance. The cutaway has
 * the opposite job: it should look like the thing. So rock is grey-brown here,
 * metal is the grey of iron, ice is pale blue, and anything hot enough to glow
 * is drawn at the colour it actually glows.
 *
 * These are literal colours rather than theme variables on purpose — a core at
 * 5,700 K is white-hot under a light theme too.
 */

import type { InteriorLayer, TemperatureReading } from '$lib/fetch/objects/object-data';

type RGB = [number, number, number];

/** What each material looks like, not what tells it apart in a legend. */
const MATERIAL_RGB: Record<string, RGB> = {
	metal: [142, 148, 156], // iron-nickel
	sulfide: [160, 139, 79], // troilite, brassy
	silicate: [111, 95, 78], // anhydrous rock
	water: [43, 108, 176], // the ocean; ice is WATER_ICE, chosen by isIce()
	volatile_ice: [214, 232, 238], // CO₂, N₂, CH₄ frosts
	organic: [63, 52, 43], // carbonaceous matter
	hydrogen: [201, 183, 154],
	helium: [232, 222, 208],
	heavy_elements: [93, 83, 72]
};

/** Water ice, which is a different colour from the ocean under it. */
const WATER_ICE: RGB = [200, 224, 240];

const FALLBACK: RGB = [120, 120, 120];

/**
 * The colour a black body of this temperature glows, from the usual
 * approximation to the Planckian locus.
 *
 * Clamped at both ends: below ~1,000 K nothing visibly glows, and past ~9,000 K
 * Wien's law puts the peak in the ultraviolet, so the approximation stops
 * describing a colour anyone could see. The Sun's 15.5 MK core is drawn at that
 * ceiling rather than extrapolated into a blue nobody would perceive.
 */
function blackbodyRgb(kelvin: number): RGB {
	const t = Math.min(Math.max(kelvin, 1000), 9000) / 100;
	const r = t <= 66 ? 255 : 329.698727446 * Math.pow(t - 60, -0.1332047592);
	const g =
		t <= 66
			? 99.4708025861 * Math.log(t) - 161.1195681661
			: 288.1221695283 * Math.pow(t - 60, -0.0755148492);
	const b = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
	return [clamp255(r), clamp255(g), clamp255(b)];
}

/**
 * How much of the layer's colour its own heat accounts for. Nothing glows
 * visibly below about 700 K; by 2,000 K the glow is all anyone would see. The
 * ceiling keeps a trace of the material, so a white-hot core still reads as
 * metal rather than as a hole in the chart. Earth's core really does reach the
 * temperature of the Sun's surface, and really does come out white.
 */
function glowWeight(kelvin: number): number {
	return Math.min(Math.max((kelvin - 700) / 1300, 0), 0.82);
}

/** The material a layer is mostly made of, or null where it lists none. */
function dominant(layer: InteriorLayer): string | null {
	return layer.composition[0]?.material ?? null;
}

/** Roles that state their own phase, for the layers `state` was never set on. */
const FROZEN_ROLES = new Set(['ice_shell', 'ice_mantle']);

/**
 * Whether a body's water is ice rather than ocean. Three ways to know, in
 * order of how directly the data says it: the layer's own phase, a role that
 * means "frozen" whatever `state` was set to, and failing both, a temperature
 * below freezing. Tethys is the last case — one undivided `bulk` layer of water
 * at 86 K, which would otherwise draw as an ocean.
 */
function isIce(layer: InteriorLayer, kelvin: number | null): boolean {
	if (layer.state === 'solid') return true;
	if (layer.state === 'liquid') return false;
	if (FROZEN_ROLES.has(layer.role)) return true;
	return kelvin !== null && kelvin < 273;
}

function materialRgb(layer: InteriorLayer, kelvin: number | null): RGB {
	const material = dominant(layer);
	if (material === null) return FALLBACK;
	// Ice and ocean are the same material and nothing like the same colour.
	if (material === 'water' && isIce(layer, kelvin)) return WATER_ICE;
	return MATERIAL_RGB[material] ?? FALLBACK;
}

/**
 * The fill for one shell of the cutaway.
 *
 * `kelvin` is whatever the body's own measurements give this layer, and is null
 * for every layer nobody has put a number on — most mantles. A layer with no
 * temperature is drawn at its material's colour and nothing else, so the glow
 * on the chart only ever comes from a number we hold.
 *
 * `depth` runs 0 at the surface to 1 at the centre and only darkens the shell a
 * little. Without it Mars's crust and mantle are both "silicate" and draw as one
 * undivided brown.
 */
function interiorLayerRgb(layer: InteriorLayer, kelvin: number | null, depth = 0): string {
	const base = shade(materialRgb(layer, kelvin), depth);
	if (kelvin === null) return css(base);
	return css(mix(base, blackbodyRgb(kelvin), glowWeight(kelvin)));
}

/** Lighter near the surface, darker towards the centre. */
function shade(rgb: RGB, depth: number): RGB {
	const f = 1.16 - 0.36 * Math.min(Math.max(depth, 0), 1);
	return [clamp255(rgb[0] * f), clamp255(rgb[1] * f), clamp255(rgb[2] * f)];
}

/**
 * What an atmosphere looks like from outside, keyed off what it is made of.
 *
 * A rough rule rather than a scattering calculation: carbon dioxide reads
 * butterscotch, nitrogen with methane in it reads as Titan's orange haze,
 * nitrogen without reads Earth-blue, hydrogen reads as a giant's cream. The
 * composition bars keep the per-gas categorical palette, which is a different
 * question — this one is only ever about what the sky would look like.
 */
export function skyRgb(species: { formula: string; share: number }[] | undefined): string {
	if (!species?.length) return css([150, 165, 185]);
	const ranked = [...species].sort((a, b) => b.share - a.share);
	const top = ranked[0].formula;
	const methane = species.find((s) => s.formula === 'CH4');
	if (top === 'CO2') return css([206, 158, 112]);
	if (top === 'N2') {
		// Titan, Pluto and Triton: photochemical haze from the methane, not the
		// nitrogen, is what gives the sky its colour.
		return methane && methane.share > 0.005 ? css([212, 146, 78]) : css([118, 162, 216]);
	}
	if (top === 'H2' || top === 'H' || top === 'He' || top === 'He-4') return css([214, 196, 166]);
	if (top === 'O2' || top === 'H2O') return css([176, 200, 220]);
	if (top === 'SO2') return css([222, 214, 168]);
	return css([150, 165, 185]);
}

/**
 * Shading for a plasma layer the body has no reading for — the Sun's radiative
 * and convective zones, which sit between a 15.5 MK core and a 5,772 K surface.
 *
 * The ramp between those two anchors is for the picture only. No temperature
 * derived from it is ever shown: a layer with no measured value still displays
 * none.
 */
function plasmaRgb(fraction: number, innerK: number, outerK: number): string {
	// Radius runs linearly, temperature over millions of kelvin does not.
	const k = Math.exp(Math.log(innerK) + (Math.log(outerK) - Math.log(innerK)) * fraction);
	return css(blackbodyRgb(k));
}

/** The low–high bracket a model gives where nobody has measured a value. */
export interface TemperatureBracket {
	lowK: number;
	highK: number;
}

/** The modelled core bracket among a body's readings — it belongs to the core
 *  layers and to nothing else. */
export function coreBracket(readings: TemperatureReading[]): TemperatureBracket | null {
	const low = readings.find((r) => r.part === 'core' && r.kind === 'min');
	const high = readings.find((r) => r.part === 'core' && r.kind === 'max');
	return low && high ? { lowK: low.k, highK: high.k } : null;
}

/** Anchors for shading a star's zones, which sit between two readings and have
 *  none of their own. */
export interface PlasmaRange {
	innerK: number;
	outerK: number;
}

/**
 * The fill for one band of the cutaway. An unmeasured plasma zone takes the
 * ramp between the star's core and surface anchors; everything else takes its
 * material's colour, with the glow its own reading earns.
 */
export function bandColor(
	band: { layer: InteriorLayer; outer: number; inner: number },
	bracket: TemperatureBracket | null | undefined,
	plasmaRange?: PlasmaRange
): string {
	const mid = (band.outer + band.inner) / 2;
	if (band.layer.state === 'plasma' && plasmaRange && !bracket) {
		return plasmaRgb(mid, plasmaRange.innerK, plasmaRange.outerK);
	}
	return interiorLayerRgb(band.layer, bracket ? (bracket.lowK + bracket.highK) / 2 : null, 1 - mid);
}

function mix(a: RGB, b: RGB, t: number): RGB {
	return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function css(rgb: RGB): string {
	return `rgb(${Math.round(rgb[0])} ${Math.round(rgb[1])} ${Math.round(rgb[2])})`;
}

function clamp255(v: number): number {
	return Math.min(Math.max(v, 0), 255);
}
