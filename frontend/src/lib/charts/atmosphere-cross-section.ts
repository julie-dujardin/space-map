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
	/** Where the layer starts, in km — the layer below's top. Null where that
	 *  boundary is unmeasured, so a thickness can't be claimed. */
	baseKm: number | null;
	/** The temperature at the bottom of the band — the layer below's top, or
	 *  the datum's for the lowest one. A layer's own reading is its top, so
	 *  without this the label states a boundary and reads as a layer. Null
	 *  where the profile has a gap: nothing measures Neptune between its
	 *  tropopause and its thermosphere. */
	baseTemperatureK: number | null;
	/** The same chain for pressure, which is pinned on far fewer boundaries —
	 *  Pluto's whole stack has none. */
	basePressurePa: number | null;
	/** Drawn at a fixed size rather than to scale; the label carries the real
	 *  height, where the source gives one. */
	capped: boolean;
	/** How opaque to draw it — the atmosphere thins with height and the ramp
	 *  says so without needing a legend. */
	opacity: number;
}

export interface AtmosphereProfile {
	bands: AtmosphereBand[];
	/** What height zero means on this body, for the ground label. */
	datum: AtmosphereStructure['datum'];
	/** The height the scaled part is drawn against, in km. */
	scaleKm: number;
	/** Set only where there are no boundaries at all: Callisto's exosphere,
	 *  described by how fast it thins rather than by where it stops. */
	scaleHeightKm: number | null;
}

/** Share of the chart each capped layer takes, whatever its real height. */
const CAPPED_BAND = 0.11;

/**
 * The height the drawn-to-scale part runs to — also what the interior chart's
 * atmosphere strip draws against, so the two charts agree on where the
 * atmosphere ends.
 */
export function drawableTopKm(structure: AtmosphereStructure): number | null {
	const scaled = structure.layers.filter((l) => !CAPPED_ROLES.has(l.role));
	return scaled.at(-1)?.top_km ?? null;
}

/**
 * Stack the layers bottom-up. Returns null for a body with nothing to draw —
 * an exosphere with no scale height is a fact, not a chart.
 */
export function atmosphereProfile(structure: AtmosphereStructure): AtmosphereProfile | null {
	const layers = structure.layers;
	if (!layers.length) return null;

	// Each layer's base is the one below's top, so the stack is walked before
	// it is split: a capped band still takes its base from the layer under it.
	const stack = layers.map((layer, i) => ({
		layer,
		baseKm: i === 0 ? 0 : (layers[i - 1].top_km ?? null),
		baseTemperatureK:
			(i === 0 ? structure.datum_temperature_k : layers[i - 1].top_temperature_k) ?? null,
		basePressurePa: (i === 0 ? structure.datum_pressure_pa : layers[i - 1].top_pressure_pa) ?? null
	}));
	const scaled = stack.filter((l) => !CAPPED_ROLES.has(l.layer.role));
	const capped = stack.filter((l) => CAPPED_ROLES.has(l.layer.role));
	const scaleKm = drawableTopKm(structure) ?? 0;

	// Callisto: an exosphere by itself. There is no boundary to scale against,
	// so the chart becomes the scale height and nothing else.
	if (!scaled.length || scaleKm <= 0) {
		return structure.scale_height_km
			? { bands: [], datum: structure.datum, scaleKm: 0, scaleHeightKm: structure.scale_height_km }
			: null;
	}

	// The scaled part gets what the capped bands leave it.
	const room = 1 - capped.length * CAPPED_BAND;
	const bands: AtmosphereBand[] = [];
	let base = 0;

	for (const entry of scaled) {
		// A layer with no top of its own cannot be drawn to scale; it borrows the
		// stack's top rather than collapsing to nothing.
		const topKm = entry.layer.top_km ?? scaleKm;
		const top = (topKm / scaleKm) * room;
		bands.push({
			...entry,
			base,
			top,
			capped: false,
			opacity: opacityAt(bands.length, layers.length)
		});
		base = top;
	}

	for (const entry of capped) {
		bands.push({
			...entry,
			base,
			top: base + CAPPED_BAND,
			capped: true,
			opacity: opacityAt(bands.length, layers.length)
		});
		base += CAPPED_BAND;
	}

	return {
		bands,
		datum: structure.datum,
		scaleKm,
		scaleHeightKm: structure.scale_height_km ?? null
	};
}

/** Denser at the bottom, because that is where the mass is. The floor is high
 *  enough that the top band still reads as a band on a dark background. */
function opacityAt(index: number, total: number): number {
	if (total <= 1) return 0.8;
	return 0.8 - (index / (total - 1)) * 0.45;
}
