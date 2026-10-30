/**
 * The points of the two Planets charts: mass against radius, and mass against
 * semi-major axis, both on log axes.
 *
 * A chart shows only measured values and minimum masses. An estimated value
 * comes from a mass–radius relation, so on these axes the estimates draw the
 * relation itself as a false curve. They are counted, not drawn.
 */

import type { PlanetPlotFile, PlanetPlotFlag } from '$lib/fetch/groups/planet-plot';
import { superscript } from '$lib/format/quantities';

/** The two kinds of exoplanet point. Validated as a pair against the light
 *  and the dark surface; they differ in shape too, a dot and a ring. */
export const PLANET_PLOT_COLORS = { measured: '#4f8fd0', minimum: '#c47a2c' } as const;

export type PlanetPlotKind = 'radius' | 'distance';

/** A point in data units: x and y as the chart draws them. */
export interface PlotPoint {
	x: number;
	y: number;
}

export interface SolarPlotPoint extends PlotPoint {
	id: string;
}

export interface PlanetPlotPoints {
	/** Every value measured, the mass a true mass. */
	measured: PlotPoint[];
	/** A minimum mass (m sin i), the other value measured. */
	minimum: PlotPoint[];
	/** The Solar System planets, in heliocentric order. */
	solar: SolarPlotPoint[];
	/** Planets with both values where one of them is an estimate. */
	estimated: number;
}

const MEASURED = 0;
const MINIMUM_MASS = 1;
const ESTIMATED = 2;

/** Mass on x against radius on y; semi-major axis on x against mass on y. */
export function planetPlotPoints(file: PlanetPlotFile, kind: PlanetPlotKind): PlanetPlotPoints {
	const other = kind === 'radius' ? file.radius : file.semi_major_axis;
	const otherFlag = kind === 'radius' ? file.radius_flag : file.semi_major_axis_flag;
	const out: PlanetPlotPoints = { measured: [], minimum: [], solar: [], estimated: 0 };
	for (let i = 0; i < file.mass.length; i++) {
		const mass = file.mass[i];
		const value = other[i];
		if (mass == null || value == null || !(mass > 0) || !(value > 0)) continue;
		const massFlag: PlanetPlotFlag = file.mass_flag[i];
		const valueFlag: PlanetPlotFlag = otherFlag[i];
		if (massFlag === ESTIMATED || valueFlag === ESTIMATED) {
			out.estimated++;
			continue;
		}
		const point = kind === 'radius' ? { x: mass, y: value } : { x: value, y: mass };
		if (i < file.solar.length) out.solar.push({ ...point, id: file.solar[i] });
		else if (massFlag === MINIMUM_MASS) out.minimum.push(point);
		else if (massFlag === MEASURED) out.measured.push(point);
	}
	return out;
}

/** The smallest and the largest value. The ticks of an axis span this range. */
export function logExtent(values: readonly number[]): [number, number] {
	let lo = Infinity;
	let hi = -Infinity;
	for (const v of values) {
		if (v < lo) lo = v;
		if (v > hi) hi = v;
	}
	if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0.1, 10];
	return [lo, hi];
}

/** The domain of a log axis that is `length` pixels long. It adds `pad`
 *  pixels at each end of the extent, so no point touches the frame. */
export function logDomain([lo, hi]: [number, number], length: number, pad = 12): [number, number] {
	const span = Math.log10(hi / lo);
	// One value, or no room for the pad, gets a decade at each end.
	const decades = span > 0 && length > 4 * pad ? (span * pad) / (length - 2 * pad) : 1;
	return [lo / 10 ** decades, hi * 10 ** decades];
}

/** Ticks of a log axis: every decade, every second one past `maxTicks`, and
 *  the 2 and 5 between them where the axis spans few decades. */
export function logTicks([lo, hi]: [number, number], maxTicks = 7): number[] {
	const first = Math.ceil(Math.log10(lo));
	const last = Math.floor(Math.log10(hi));
	const decades: number[] = [];
	for (let e = first; e <= last; e++) decades.push(e);
	const step = decades.length > maxTicks ? 2 : 1;
	const ticks = decades.filter((e) => (e - first) % step === 0).map((e) => 10 ** e);
	if (decades.length >= 3) return ticks;
	const fine: number[] = [];
	for (let e = first - 1; e <= last; e++) {
		for (const k of [1, 2, 5]) {
			const v = k * 10 ** e;
			if (v >= lo && v <= hi) fine.push(v);
		}
	}
	return fine;
}

/** 10ⁿ for a power of ten far from 1, where the digits would not fit a tick. */
export function powerOfTenLabel(v: number): string | null {
	const e = Math.round(Math.log10(v));
	if (Math.abs(v - 10 ** e) > 1e-9 * 10 ** e || (e >= -2 && e <= 3)) return null;
	return `10${superscript(e)}`;
}

/** A dot to name, in pixels, with the width of its name. */
export interface LabelledDot {
	px: number;
	py: number;
	width: number;
}

/** Where a name goes: its anchor point and how the text hangs off it. */
export interface PlacedLabel {
	x: number;
	y: number;
	anchor: 'start' | 'middle' | 'end';
}

interface Box {
	x0: number;
	y0: number;
	x1: number;
	y1: number;
}

function overlaps(a: Box, b: Box): boolean {
	return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1;
}

/**
 * Names for a few dots, each beside its own dot where it hits no other name,
 * no other named dot and no edge of the plot. Right of the dot first, then
 * left, above, below and the corners. The first spot inside the plot is the
 * fallback when every spot is taken.
 */
export function placeLabels(
	dots: readonly LabelledDot[],
	plotW: number,
	plotH: number,
	{ gap = 6, lineHeight = 10, dotRadius = 4 } = {}
): PlacedLabel[] {
	const half = lineHeight / 2;
	const dotBoxes = dots.map((d) => ({
		x0: d.px - dotRadius,
		y0: d.py - dotRadius,
		x1: d.px + dotRadius,
		y1: d.py + dotRadius
	}));
	const placed: Box[] = [];
	return dots.map((d, i) => {
		const w = d.width;
		const diag = gap * 0.7;
		const spots: [PlacedLabel, Box][] = [
			[{ x: d.px + gap, y: d.py, anchor: 'start' }, box(d.px + gap, d.py - half, w)],
			[{ x: d.px - gap, y: d.py, anchor: 'end' }, box(d.px - gap - w, d.py - half, w)],
			[
				{ x: d.px, y: d.py - gap - half, anchor: 'middle' },
				box(d.px - w / 2, d.py - gap - 2 * half, w)
			],
			[{ x: d.px, y: d.py + gap + half, anchor: 'middle' }, box(d.px - w / 2, d.py + gap, w)],
			[
				{ x: d.px + diag, y: d.py - diag - half, anchor: 'start' },
				box(d.px + diag, d.py - diag - 2 * half, w)
			],
			[
				{ x: d.px + diag, y: d.py + diag + half, anchor: 'start' },
				box(d.px + diag, d.py + diag, w)
			],
			[
				{ x: d.px - diag, y: d.py - diag - half, anchor: 'end' },
				box(d.px - diag - w, d.py - diag - 2 * half, w)
			],
			[
				{ x: d.px - diag, y: d.py + diag + half, anchor: 'end' },
				box(d.px - diag - w, d.py + diag, w)
			]
		];
		const inside = spots.filter(
			([, b]) => b.x0 >= 0 && b.y0 >= 0 && b.x1 <= plotW && b.y1 <= plotH
		);
		const free = inside.find(
			([, b]) =>
				!placed.some((p) => overlaps(p, b)) &&
				!dotBoxes.some((other, j) => j !== i && overlaps(other, b))
		);
		const [label, b] = free ?? inside[0] ?? spots[0];
		placed.push(b);
		return label;
	});

	function box(x0: number, y0: number, w: number): Box {
		return { x0, y0, x1: x0 + w, y1: y0 + lineHeight };
	}
}
