/**
 * Geometry for the atmosphere cross-section: a stack of layers drawn to scale
 * by height, with the tenuous outer ones capped.
 *
 * Earth's exosphere reaches ~10,000 km against a 12 km troposphere. Drawn to
 * scale on one axis the weather layer is a hairline and everything readable is
 * vacuum, so the chart runs to scale only up to the top of the highest layer
 * that is not a thermosphere, exosphere or corona; those three are capped to a
 * fixed band each and carry their real height in the label. They hold
 * essentially none of the atmosphere's mass, which is what makes that honest
 * rather than convenient.
 */

import type { AtmosphereLayer, AtmosphereStructure } from '$lib/fetch/objects/object-data';

/** Too thin to draw against the layers below. Kept in sync with
 *  `tests/export/test_atmosphere_facts.py`, which asserts every body still has
 *  a boundary left underneath to set the scale by. */
const CAPPED_ROLES = new Set(['thermosphere', 'exosphere', 'corona']);

export interface AtmosphereBand {
	layer: AtmosphereLayer;
	/** Fraction of the drawn height, 0–1. Bottom and top edges. */
	base: number;
	top: number;
	/** Drawn at a fixed size rather than to scale; the label carries the real
	 *  height, where the source gives one. */
	capped: boolean;
	/** How opaque to draw it — the atmosphere thins with height and the ramp
	 *  says so without needing a legend. */
	opacity: number;
}

export interface AtmosphereProfile {
	bands: AtmosphereBand[];
	/** The height the scaled part is drawn against, in km. */
	scaleKm: number;
	/** Set only where there are no boundaries at all: Callisto's exosphere,
	 *  described by how fast it thins rather than by where it stops. */
	scaleHeightKm: number | null;
}

/** Share of the chart each capped layer takes, whatever its real height. */
const CAPPED_BAND = 0.11;

/**
 * Stack the layers bottom-up. Returns null for a body with nothing to draw —
 * an exosphere with no scale height is a fact, not a chart.
 */
export function atmosphereProfile(structure: AtmosphereStructure): AtmosphereProfile | null {
	const layers = structure.layers;
	if (!layers.length) return null;

	const scaled = layers.filter((l) => !CAPPED_ROLES.has(l.role));
	const capped = layers.filter((l) => CAPPED_ROLES.has(l.role));
	const scaleKm = scaled.at(-1)?.top_km ?? 0;

	// Callisto: an exosphere by itself. There is no boundary to scale against,
	// so the chart becomes the scale height and nothing else.
	if (!scaled.length || scaleKm <= 0) {
		return structure.scale_height_km
			? { bands: [], scaleKm: 0, scaleHeightKm: structure.scale_height_km }
			: null;
	}

	// The scaled part gets what the capped bands leave it.
	const room = 1 - capped.length * CAPPED_BAND;
	const bands: AtmosphereBand[] = [];
	let base = 0;

	for (const layer of scaled) {
		// A layer with no top of its own cannot be drawn to scale; it borrows the
		// stack's top rather than collapsing to nothing.
		const topKm = layer.top_km ?? scaleKm;
		const top = (topKm / scaleKm) * room;
		bands.push({
			layer,
			base,
			top,
			capped: false,
			opacity: opacityAt(bands.length, layers.length)
		});
		base = top;
	}

	for (const layer of capped) {
		bands.push({
			layer,
			base,
			top: base + CAPPED_BAND,
			capped: true,
			opacity: opacityAt(bands.length, layers.length)
		});
		base += CAPPED_BAND;
	}

	return { bands, scaleKm, scaleHeightKm: structure.scale_height_km ?? null };
}

/** Denser at the bottom, because that is where the mass is. The floor is high
 *  enough that the top band still reads as a band on a dark background. */
function opacityAt(index: number, total: number): number {
	if (total <= 1) return 0.8;
	return 0.8 - (index / (total - 1)) * 0.45;
}

/**
 * The height the interior chart's atmosphere strip draws to — the same top the
 * profile above is scaled against, so the two charts agree on where the
 * atmosphere ends.
 */
export function drawableTopKm(structure: AtmosphereStructure): number | null {
	const scaled = structure.layers.filter((l) => !CAPPED_ROLES.has(l.role));
	return scaled.at(-1)?.top_km ?? null;
}

export { CAPPED_ROLES };
