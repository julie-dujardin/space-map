/**
 * Geometry for the interior cross-section: a quarter disc of nested shells,
 * drawn to scale by radius.
 *
 * Radii are normalized to the **outermost layer**, not to the body's mean
 * radius. The two are different numbers — a layer model carries its source's
 * own R, which is 1560.8 km for Europa where the exported radius is 1565 — and
 * normalizing to the body would leave a gap or an overshoot at the surface on
 * every body whose paper picked a different R.
 */

import type { InteriorLayer } from '$lib/fetch/objects/object-data';

export interface InteriorBand {
	layer: InteriorLayer;
	/** Fraction of the drawn radius, 0–1, outer edge and inner edge. */
	outer: number;
	inner: number;
	/** Below the surface, in km — how anyone actually places a layer. The core
	 *  runs to the centre, so its far end is the body's radius. */
	depthFromKm: number;
	depthToKm: number;
	thicknessKm: number;
}

export interface AtmosphereStrip {
	/** Where the atmosphere's top sits, as a fraction of the body's radius —
	 *  0.013 on Earth, whose whole drawable atmosphere is 84 km against 6371. */
	height: number;
	/** The real height, for the label. */
	km: number;
}

export interface InteriorCrossSection {
	bands: InteriorBand[];
	/** The radius every band is a fraction of. */
	radiusKm: number;
	/** Absent on the giants and the Sun, where the outermost layer already *is*
	 *  the atmosphere and a strip on top of it would draw the same gas twice. */
	atmosphere: AtmosphereStrip | null;
}

/**
 * Nest the layers into bands. Each one runs from its own radius down to the
 * next layer's, and the innermost closes on the centre.
 *
 * `atmosphereKm` is the height the atmosphere chart draws to scale — pass it to
 * get the strip, or omit it on a body with no atmosphere worth a band.
 */
export function crossSection(
	layers: InteriorLayer[],
	options: { atmosphereKm?: number; hasOwnAtmosphere?: boolean } = {}
): InteriorCrossSection | null {
	if (!layers.length) return null;
	const radiusKm = layers[0].outer_radius_km;
	if (!(radiusKm > 0)) return null;

	const bands = layers.map((layer, i) => {
		const innerKm = i + 1 < layers.length ? layers[i + 1].outer_radius_km : 0;
		return {
			layer,
			outer: layer.outer_radius_km / radiusKm,
			inner: innerKm / radiusKm,
			depthFromKm: radiusKm - layer.outer_radius_km,
			depthToKm: radiusKm - innerKm,
			thicknessKm: layer.outer_radius_km - innerKm
		};
	});

	// The giants and the Sun have no separate envelope to draw: their outermost
	// layer is the atmosphere, and the split into two charts only exists for
	// bodies whose thick rock and thin air cannot share one scale.
	const atmosphere =
		options.hasOwnAtmosphere === false && options.atmosphereKm && options.atmosphereKm > 0
			? { height: options.atmosphereKm / radiusKm, km: options.atmosphereKm }
			: null;

	return { bands, radiusKm, atmosphere };
}

/**
 * SVG path for one band of a quarter disc centred on (cx, cy), opening up and
 * to the right. An inner radius of 0 closes on the centre instead of leaving a
 * hole, which is what the innermost core needs.
 */
export function bandPath(
	band: { outer: number; inner: number },
	cx: number,
	cy: number,
	r: number
) {
	const ro = band.outer * r;
	const ri = band.inner * r;
	if (ri <= 0) return `M ${cx} ${cy} L ${cx + ro} ${cy} A ${ro} ${ro} 0 0 0 ${cx} ${cy - ro} Z`;
	return (
		`M ${cx + ri} ${cy} L ${cx + ro} ${cy} ` +
		`A ${ro} ${ro} 0 0 0 ${cx} ${cy - ro} ` +
		`L ${cx} ${cy - ri} ` +
		`A ${ri} ${ri} 0 0 1 ${cx + ri} ${cy} Z`
	);
}
