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
	/** Slice of the disc's arc the band occupies, 0–1, where 1 is the vertical
	 *  edge the radius axis runs up. A shell takes the whole quarter; a patch
	 *  takes its share of the surface — see `arcSpan`. */
	from: number;
	to: number;
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
		// A shell ends where the next one begins; a patch carries its own floor,
		// because what is under it is not the next thing in the list. Earth's
		// ocean is followed by the continental crust and floored by the sea bed.
		const innerKm =
			layer.base_radius_km ?? (i + 1 < layers.length ? layers[i + 1].outer_radius_km : 0);
		return {
			layer,
			outer: layer.outer_radius_km / radiusKm,
			inner: innerKm / radiusKm,
			...arcSpan(layer),
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
 * Which slice of the arc a layer gets.
 *
 * The disc's arc is read as the body's *surface*, so a layer that covers part
 * of it is drawn across part of the arc rather than as a thin complete shell.
 * That is the only way to draw Earth honestly: its two crusts are not stacked,
 * they are 41% granite and 59% basalt lying side by side, and the ocean spills
 * across the join because the continental shelves are drowned.
 *
 * Wet layers hang off the vertical edge — the one the radius axis runs up and
 * the depths are labelled against — so the axis reads down through sea level
 * the way every depth in the panel is measured. The continents take the other
 * end. The two crusts then tile the arc, and the ocean, wider than the sea
 * floor it sits on, laps over onto the continental side by exactly the shelves.
 */
const WET: ReadonlySet<string> = new Set(['ocean', 'sea', 'oceanic_crust']);

function arcSpan(layer: InteriorLayer): { from: number; to: number } {
	const share = layer.area_fraction;
	if (share === undefined) return { from: 0, to: 1 };
	return WET.has(layer.role) ? { from: 1 - share, to: 1 } : { from: 0, to: share };
}

/**
 * Group the bands the way they are actually arranged: a run of layers that
 * share a depth but not a place goes in one row, everything else on its own.
 *
 * Earth's two crusts are the case. Listed one under the other they read as a
 * stack — 41 km of granite with 6 km of basalt somewhere inside it — which is
 * the one thing about Earth's crust that is not true. The ocean is not in the
 * row: it overlaps both of them, because the shelves are drowned continent.
 */
export function layerRows(bands: InteriorBand[]): InteriorBand[][] {
	const rows: InteriorBand[][] = [];
	for (const band of bands) {
		const row = rows.at(-1);
		const beside =
			row !== undefined &&
			band.layer.area_fraction !== undefined &&
			row.every((other) => other.to <= band.from || band.to <= other.from);
		if (beside) row.push(band);
		else rows.push([band]);
	}
	return rows;
}

/** A point on the quarter disc: `s` runs 0 at the horizontal to 1 at the
 *  vertical edge. */
function point(cx: number, cy: number, r: number, s: number): string {
	const angle = (s * Math.PI) / 2;
	return `${cx + r * Math.cos(angle)} ${cy - r * Math.sin(angle)}`;
}

/**
 * SVG path for one band of a quarter disc centred on (cx, cy), opening up and
 * to the right. An inner radius of 0 closes on the centre instead of leaving a
 * hole, which is what the innermost core needs.
 *
 * `from`/`to` cut the band down to its slice of the arc; a band without them
 * spans the whole quarter. Every arc here is at most a quarter turn, so the
 * large-arc flag is always 0.
 */
export function bandPath(
	band: { outer: number; inner: number; from?: number; to?: number },
	cx: number,
	cy: number,
	r: number
) {
	const ro = band.outer * r;
	const ri = band.inner * r;
	const s0 = band.from ?? 0;
	const s1 = band.to ?? 1;
	const outerFrom = point(cx, cy, ro, s0);
	const outerTo = point(cx, cy, ro, s1);
	if (ri <= 0) return `M ${cx} ${cy} L ${outerFrom} A ${ro} ${ro} 0 0 0 ${outerTo} Z`;
	return (
		`M ${point(cx, cy, ri, s0)} L ${outerFrom} ` +
		`A ${ro} ${ro} 0 0 0 ${outerTo} ` +
		`L ${point(cx, cy, ri, s1)} ` +
		`A ${ri} ${ri} 0 0 1 ${point(cx, cy, ri, s0)} Z`
	);
}
