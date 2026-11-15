/**
 * What a chart draws over its sky: its lines, the places of its stars, and the
 * names that the painted sky ranks. The drawer's chart and the SDK's chart
 * both draw from this.
 */

import { extrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import type { ChartStar, FigureChart } from './figure';
import { figureAspect, fillFrame, fitFrame, project, type ChartFrame } from './frame';
import { placeNames, type LabelBox, type Segment } from './labels';
import { PAINT_RATIO, paintedFlux, type Pixels } from './sky';

/** A frame under this size on its short side holds no names. */
export const LABEL_MIN_PX = 150;
/** One name per this many square pixels. */
const LABEL_AREA_PX = 11000;
export const LABEL_MAX = 14;
/** A chart that fills its box has the room of a screen. */
export const FILL_LABEL_MAX = 40;
const LABEL_HEIGHT_PX = 13;
const LABEL_GAP_PX = 6;
/** A line stops short of its star, so the star shows. */
const STAR_CLEAR_PX = 5;
/** A chart with no names needs no room for them, and its lines are short. */
const BARE_MARGIN = 0.12;
const BARE_CLEAR_PX = 2.5;
export const STAND_IN_RING_PX = 6;
/** Radius of the disc that measures a star, in CSS pixels. */
const FLUX_RADIUS_PX = 1.5;
/** Under this painted light, a neighbour does not stand out of the sky.
 *  Counted in a picture of {@link PAINT_RATIO}. */
const NEIGHBOUR_MIN_FLUX = 400;
/** A new size waits this long for the next one, so a drag paints once. */
export const SETTLE_MS = 120;

export interface FrameChoice {
	/** Width over height, where the chart sets its own height. */
	ratio: number;
	frame: ChartFrame | null;
}

/**
 * The frame of a chart `width` wide. With `fill` it has the size of its box,
 * `height` high. Else its height follows `aspect`, or the figure's own shape
 * within the two limits.
 */
export function chooseFrame(
	chart: FigureChart | null,
	options: {
		width: number;
		height: number;
		fill: boolean;
		labels: boolean;
		aspect?: number;
		minAspect: number;
		maxAspect: number;
		clear?: readonly [number, number];
	}
): FrameChoice {
	const { width, fill, labels, clear } = options;
	const ratio =
		options.aspect ??
		(chart?.points.length
			? figureAspect(chart.points, options.minAspect, options.maxAspect)
			: 4 / 3);
	const height = fill ? options.height : Math.round(width / ratio);
	if (!chart?.points.length || width <= 0 || height <= 0) return { ratio, frame: null };
	if (fill) return { ratio, frame: fillFrame(chart.points, { width, height, clear }) };
	return {
		ratio,
		frame: fitFrame(chart.points, { width, height, margin: labels ? undefined : BARE_MARGIN })
	};
}

/** Where a frame puts the lines, stars and stand-ins of a chart. */
export interface ChartPoints {
	segments: Segment[];
	stars: [number, number][];
	standIns: [number, number][];
}

export function chartPoints(frame: ChartFrame, chart: FigureChart): ChartPoints {
	return {
		segments: chart.lines.map(([a, b]) => [...project(frame, a), ...project(frame, b)] as const),
		stars: chart.stars.map(({ direction }) => project(frame, direction)),
		standIns: chart.standIns.map(({ direction }) => project(frame, direction))
	};
}

/** The lines as one SVG path, each cut short at both ends. */
export function linePath(segments: readonly Segment[], labels: boolean): string {
	return segments
		.map(([x1, y1, x2, y2]) => {
			const length = Math.hypot(x2 - x1, y2 - y1);
			if (length === 0) return '';
			// A short line keeps half of its length.
			const clear = Math.min(labels ? STAR_CLEAR_PX : BARE_CLEAR_PX, length / 4) / length;
			const ux = (x2 - x1) * clear;
			const uy = (y2 - y1) * clear;
			return `M${(x1 + ux).toFixed(1)} ${(y1 + uy).toFixed(1)}L${(x2 - ux).toFixed(1)} ${(y2 - uy).toFixed(1)}`;
		})
		.join('');
}

/** A star that wants a name, at its place on the chart. */
export interface NamedPoint {
	x: number;
	y: number;
	name: string;
	/** Object.id of a star. Absent on a member that has no page. */
	id?: string;
}

/** A star of the chart in the frame, with its light in the painted sky. */
export interface MeasuredStar {
	star: ChartStar;
	x: number;
	y: number;
	flux: number;
	/** Null for a star that has no name to show. */
	name: string | null;
}

/** The names that a paint found for its frame, before they are laid out. */
export interface ChartNames {
	frame: ChartFrame;
	/** The most names of members. */
	limit: number;
	/** Members: the stand-ins, then the stars, the brightest first. */
	own: NamedPoint[];
	/** Neighbours that stand out as much, the brightest first. */
	around: NamedPoint[];
	/** The members in the frame, the brightest first, named or not. */
	members: MeasuredStar[];
	/** The neighbours that stand out, named or not. */
	neighbours: MeasuredStar[];
	segments: Segment[];
	points: (readonly [number, number])[];
}

/** The names of a chart with none. */
export function noNames(frame: ChartFrame, points: ChartPoints): ChartNames {
	return {
		frame,
		limit: 0,
		own: [],
		around: [],
		members: [],
		neighbours: [],
		segments: points.segments,
		points: [...points.stars, ...points.standIns]
	};
}

/** The stars inside the frame, the brightest in the painted sky first. */
function measureStars(
	at: ChartFrame,
	stars: readonly ChartStar[],
	pixels: Pixels | null
): Omit<MeasuredStar, 'name'>[] {
	const scale = pixels ? pixels.width / at.width : 1;
	return stars
		.map((star) => {
			const [x, y] = project(at, star.direction);
			const flux = pixels ? paintedFlux(pixels, x * scale, y * scale, FLUX_RADIUS_PX * scale) : 0;
			return { star, x, y, flux };
		})
		.filter(({ x, y }) => x >= 0 && y >= 0 && x <= at.width && y <= at.height)
		.sort((a, b) => b.flux - a.flux);
}

function median(values: number[]): number {
	const sorted = [...values].sort((a, b) => a - b);
	return sorted[sorted.length >> 1] ?? 0;
}

/** A namer that asks once per star. */
export function rememberNames(
	name: (star: ChartStar) => Promise<string | null>
): (star: ChartStar) => Promise<string | null> {
	const asked = new Map<number, Promise<string | null>>();
	return (star) => {
		let held = asked.get(star.id);
		if (!held) asked.set(star.id, (held = name(star).catch(() => null)));
		return held;
	};
}

export interface NameSearch {
	frame: ChartFrame;
	chart: FigureChart;
	/** The painted sky; null for a chart with no sky. */
	pixels: Pixels | null;
	points: ChartPoints;
	/** The most names of members. */
	most: number;
	neighbours: boolean;
	name: (star: ChartStar) => Promise<string | null>;
	/** False once a newer search has started. */
	current: () => boolean;
}

/**
 * The names of a chart: the members first, the brightest first, then the
 * neighbours that stand out as much. `found` hears the members, then the
 * members with the neighbours. A search that is no longer current stops.
 */
export async function findNames(
	search: NameSearch,
	found: (names: ChartNames) => void
): Promise<void> {
	const { frame: at, chart, pixels, points } = search;
	const members = measureStars(at, chart.stars, pixels);
	const memberNames = await Promise.all(members.map(({ star }) => search.name(star)));
	if (!search.current()) return;
	const limit = Math.min(Math.round((at.width * at.height) / LABEL_AREA_PX), search.most);
	const own: ChartNames = {
		...noNames(at, points),
		limit,
		members: members.map((star, i) => ({ ...star, name: memberNames[i] })),
		// A member with no star has no light to rank it by, and its ring needs a name.
		own: [
			...chart.standIns.flatMap(({ name }, i) =>
				name ? [{ x: points.standIns[i][0], y: points.standIns[i][1], name }] : []
			),
			...members.flatMap(({ star, x, y }, i) => {
				const name = memberNames[i];
				return name ? [{ x, y, name, id: extrasolarObjectId(star.id) }] : [];
			})
		]
	};
	found(own);
	// With no sky, no star is known to be bright.
	if (!pixels || !search.neighbours) return;
	const floor = Math.max(
		median(members.map(({ flux }) => flux)),
		NEIGHBOUR_MIN_FLUX * (pixels.width / at.width / PAINT_RATIO) ** 2
	);
	const around = measureStars(at, chart.neighbours, pixels)
		.filter(({ flux }) => flux >= floor)
		.slice(0, limit);
	const aroundNames = await Promise.all(around.map(({ star }) => search.name(star)));
	if (!search.current()) return;
	found({
		...own,
		neighbours: around.map((star, i) => ({ ...star, name: aroundNames[i] })),
		around: around.flatMap(({ star, x, y }, i) => {
			const name = aroundNames[i];
			return name ? [{ x, y, name, id: extrasolarObjectId(star.id) }] : [];
		})
	});
}

/** A name in its place. */
export interface PlacedName extends LabelBox {
	name: string;
	id?: string;
	neighbour: boolean;
}

function layout(
	names: ChartNames,
	wanted: readonly NamedPoint[],
	most: number,
	textWidth: (text: string) => number,
	taken: readonly LabelBox[],
	neighbour: boolean
): PlacedName[] {
	return placeNames(
		wanted.map(({ x, y, name }) => ({ x, y, width: textWidth(name), height: LABEL_HEIGHT_PX })),
		{
			width: names.frame.width,
			height: names.frame.height,
			gap: LABEL_GAP_PX,
			limit: most,
			segments: names.segments,
			points: names.points,
			taken
		}
	).map(({ index, ...box }) => ({
		...box,
		name: wanted[index].name,
		id: wanted[index].id,
		neighbour
	}));
}

/** The names laid out, the members first. No name goes on a `taken` box. */
export function layoutNames(
	names: ChartNames,
	textWidth: (text: string) => number,
	taken: readonly LabelBox[] = []
): PlacedName[] {
	const own = layout(names, names.own, names.limit, textWidth, taken, false);
	const others = layout(
		names,
		names.around,
		Math.ceil(names.limit / 2),
		textWidth,
		[...taken, ...own],
		true
	);
	return [...own, ...others];
}

/** Width of a name in the chart's font: 500 weight, 11 px. */
export function nameWidth(): (text: string, family: string) => number {
	let pen: CanvasRenderingContext2D | null = null;
	return (text, family) => {
		pen ??= document.createElement('canvas').getContext('2d');
		if (!pen) return text.length * 6;
		pen.font = `500 11px ${family}`;
		return Math.ceil(pen.measureText(text).width);
	};
}
