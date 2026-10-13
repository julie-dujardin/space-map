/**
 * Which tiles a flat map draws: pure geometry of the tile grids
 * (docs/export-format/tiles.md), kept apart from the pictures so it can be
 * tested.
 *
 * A window is a rectangle of pixels of one level of one chart. It covers the
 * frame, and the map draws it over the whole-body picture of its layer.
 */

import {
	CAP_EDGE,
	CHART_FOLDER,
	MAP,
	NORTH,
	SOUTH,
	chartColumns,
	chartRows,
	patchOfTile,
	type Chart,
	type PatchRange
} from '$lib/scene/lod/tile-window';

const DEG = Math.PI / 180;

/** How large a tile pixel is drawn, in pixels of the frame, before the next
 *  level takes over. */
const MAX_STRETCH = 1.25;

/** Pixels a window can hold. A frame that needs more gets a coarser level. */
export const MAX_WINDOW_PIXELS = 8_000_000;

/** Samples along each side of the frame. They find its extent on a chart. */
const GRID = 17;

/** Ground a window holds past each side of a frame that can move, as a
 *  fraction of the frame. A short pan then needs no new window. */
const MARGIN = 0.15;

/** A cap is used when it covers the frame with this fraction of the pixels
 *  that the map needs, or less. */
const CAP_GAIN = 0.75;

/** What the plan reads of a tile pyramid. */
export interface Pyramid<P extends PatchRange = PatchRange> {
	tile_size: number;
	max_level: number;
	patches?: readonly P[];
}

/** The frame of a flat map, as the plan sees it. */
export interface FrameSample {
	/** The place at a fraction of the frame from its top-left corner, or null
	 *  off the world. */
	place(fx: number, fy: number): [lon: number, lat: number] | null;
	/** The angle on the ground that one pixel covers at the middle of the
	 *  frame, in radians. */
	step: number;
	/** A pole that is a point inside the frame. All meridians meet there. */
	north?: boolean;
	south?: boolean;
}

export interface WindowSpec {
	chart: Chart;
	level: number;
	/** North-west pixel of the window on its chart. A map column is not
	 *  wrapped: a window that crosses the ±180° meridian continues past the
	 *  edge of the chart. */
	x0: number;
	y0: number;
	width: number;
	height: number;
	/** The part that the frame shows: first and last column, first and last row. */
	inner: [x0: number, y0: number, x1: number, y1: number];
}

export interface WindowTile<P> {
	cap: (typeof CHART_FOLDER)[number];
	level: number;
	x: number;
	y: number;
	/** Where the north-west pixel of the tile goes in the window. */
	dx: number;
	dy: number;
	/** The patch of a tile past the finest level of the pyramid. */
	patch?: P;
}

interface Extent {
	minX: number;
	maxX: number;
	minY: number;
	maxY: number;
}

/**
 * Where a place falls on `chart`, as fractions of its width and height from
 * its north-west corner. A place past the sides of a cap has fractions
 * outside 0..1.
 */
export function chartFraction(chart: Chart, lon: number, lat: number): [x: number, y: number] {
	if (chart === MAP) return [(lon + 180) / 360, (90 - lat) / 180];
	const side = chart === NORTH ? 1 : -1;
	const r = (0.5 * Math.tan(((90 - side * lat) * DEG) / 2)) / CAP_EDGE;
	return [0.5 + r * Math.cos(lon * DEG), 0.5 - side * r * Math.sin(lon * DEG)];
}

/** The first level whose pixels are small enough for a frame with this
 *  ground step. Not limited to the levels of a pyramid. */
export function levelForStep(step: number, tileSize: number): number {
	return Math.ceil(Math.log2((2 * Math.PI) / (step * MAX_STRETCH * 2 * tileSize)));
}

/** The ground step of one pixel of `level`, at the equator, in radians. */
export function stepOfLevel(level: number, tileSize: number): number {
	return (2 * Math.PI) / (2 * tileSize * 2 ** level);
}

/** The finest level that has a tile at a place: the finest of the pyramid,
 *  or that of a patch over the place. */
export function finestLevelAt(pyramid: Pyramid, lon: number, lat: number): number {
	const [across, fy] = chartFraction(MAP, lon, lat);
	// A longitude can be given past ±180°.
	const fx = across - Math.floor(across);
	let finest = pyramid.max_level;
	for (const patch of pyramid.patches ?? []) {
		if (patch.max_level <= finest) continue;
		const x = Math.floor(fx * chartColumns(MAP, patch.max_level));
		const y = Math.floor(fy * chartRows(MAP, patch.max_level));
		if (patchOfTile([patch], patch.max_level, x, y)) finest = patch.max_level;
	}
	return finest;
}

/** The extent of the frame on `chart`, in fractions of the chart. Map columns
 *  count from the middle of the frame, so the extent can cross the ±180°
 *  meridian. Null when the frame leaves a cap. */
function extentOn(
	chart: Chart,
	frame: FrameSample,
	places: readonly [number, number][],
	centre: [number, number]
): Extent | null {
	const [cx] = chartFraction(MAP, centre[0], centre[1]);
	const extent: Extent = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
	for (const [lon, lat] of places) {
		const [across, y] = chartFraction(chart, lon, lat);
		if (chart !== MAP && (across < 0 || across > 1 || y < 0 || y > 1)) return null;
		const x = chart === MAP ? across - Math.round(across - cx) : across;
		extent.minX = Math.min(extent.minX, x);
		extent.maxX = Math.max(extent.maxX, x);
		extent.minY = Math.min(extent.minY, y);
		extent.maxY = Math.max(extent.maxY, y);
	}
	// The samples miss the ground between them.
	const padX = (extent.maxX - extent.minX) / (GRID - 1);
	const padY = (extent.maxY - extent.minY) / (GRID - 1);
	extent.minX -= padX;
	extent.maxX += padX;
	extent.minY -= padY;
	extent.maxY += padY;
	if (chart === MAP && (frame.north || frame.south)) {
		extent.minX = cx - 0.5;
		extent.maxX = cx + 0.5;
		if (frame.north) extent.minY = 0;
		if (frame.south) extent.maxY = 1;
	}
	return extent;
}

/** The pixels of `level` that cover `extent`, with `margin` of it added on each side. */
function windowOver(
	chart: Chart,
	level: number,
	tileSize: number,
	extent: Extent,
	margin: number
): WindowSpec {
	const chartWidth = chartColumns(chart, level) * tileSize;
	const chartHeight = chartRows(chart, level) * tileSize;
	const rect = (grow: number): [number, number, number, number] => {
		const growX = (extent.maxX - extent.minX) * grow;
		const growY = (extent.maxY - extent.minY) * grow;
		let x0 = Math.floor((extent.minX - growX) * chartWidth);
		let x1 = Math.ceil((extent.maxX + growX) * chartWidth);
		if (chart !== MAP) {
			x0 = Math.max(x0, 0);
			x1 = Math.min(x1, chartWidth);
		} else if (x1 - x0 > chartWidth) {
			x0 = Math.round(((extent.minX + extent.maxX) / 2) * chartWidth - chartWidth / 2);
			x1 = x0 + chartWidth;
		}
		const y0 = Math.max(Math.floor((extent.minY - growY) * chartHeight), 0);
		const y1 = Math.min(Math.ceil((extent.maxY + growY) * chartHeight), chartHeight);
		return [x0, y0, x1, y1];
	};
	const [x0, y0, x1, y1] = rect(margin);
	const inner = rect(0);
	return {
		chart,
		level,
		x0,
		y0,
		width: Math.max(x1 - x0, 1),
		height: Math.max(y1 - y0, 1),
		inner: [inner[0], inner[1], inner[2] - 1, inner[3] - 1]
	};
}

/** The window over `extent` with `margin`, or without one when the margin
 *  does not fit. Undefined when the frame alone does not fit. */
function fitted(
	chart: Chart,
	level: number,
	tileSize: number,
	extent: Extent,
	margin: number
): WindowSpec | undefined {
	for (const grow of [margin, 0]) {
		const spec = windowOver(chart, level, tileSize, extent, grow);
		if (spec.width * spec.height <= MAX_WINDOW_PIXELS) return spec;
	}
	return undefined;
}

/** Whether a tile of `patch` is in the extent of the frame on the map. */
function reaches(patch: PatchRange, extent: Extent): boolean {
	const columns = chartColumns(MAP, patch.max_level);
	const rows = chartRows(MAP, patch.max_level);
	const south = (patch.y[1] + 1) / rows;
	if (patch.y[0] / rows > extent.maxY || south < extent.minY) return false;
	let west = patch.x[0] / columns;
	// The copy of the patch nearest the frame.
	west -= Math.round(west - (extent.minX + extent.maxX) / 2);
	const east = west + (patch.x[1] + 1 - patch.x[0]) / columns;
	return west <= extent.maxX && east >= extent.minX;
}

/**
 * The windows that a frame draws, finest first. Empty when the whole-body
 * picture is fine enough: `firstLevel` is the first level that holds more.
 *
 * A level past the finest of the pyramid has tiles on a patch only. Its
 * window comes with one of the finest level of the pyramid, for the ground
 * around the patch.
 *
 * `moves` is false for a frame that stays in place. Its windows have no margin.
 */
export function planWindows(
	pyramid: Pyramid,
	frame: FrameSample,
	firstLevel: number,
	moves = true
): WindowSpec[] {
	const margin = moves ? MARGIN : 0;
	const centre = frame.place(0.5, 0.5);
	if (!centre || !(frame.step > 0)) return [];
	const places: [number, number][] = [];
	for (let j = 0; j < GRID; j++) {
		for (let i = 0; i < GRID; i++) {
			const place = frame.place(i / (GRID - 1), j / (GRID - 1));
			if (place) places.push(place);
		}
	}
	const onMap = extentOn(MAP, frame, places, centre)!;
	const wanted = levelForStep(frame.step, pyramid.tile_size);
	const specs: WindowSpec[] = [];

	let finest = pyramid.max_level;
	for (const patch of pyramid.patches ?? []) {
		if (patch.max_level > finest && reaches(patch, onMap)) finest = patch.max_level;
	}
	for (let level = Math.min(wanted, finest); level > pyramid.max_level; level--) {
		const spec = fitted(MAP, level, pyramid.tile_size, onMap, margin);
		if (!spec) continue;
		specs.push(spec);
		break;
	}

	const cap = centre[1] >= 0 ? NORTH : SOUTH;
	const onCap = extentOn(cap, frame, places, centre);
	for (let level = Math.min(wanted, pyramid.max_level); level >= firstLevel; level--) {
		const map = fitted(MAP, level, pyramid.tile_size, onMap, margin);
		const polar =
			onCap && level >= 1 ? fitted(cap, level, pyramid.tile_size, onCap, margin) : undefined;
		const mapPixels = map ? map.width * map.height : Infinity;
		const spec =
			polar && polar.width * polar.height <= mapPixels * CAP_GAIN ? polar : (map ?? polar);
		if (!spec) continue;
		specs.push(spec);
		break;
	}
	return specs;
}

/** The tiles that a window holds, nearest its middle first. A level past the
 *  finest of the pyramid gives the tiles of its patches only. */
export function windowTiles<P extends PatchRange>(
	spec: WindowSpec,
	pyramid: Pyramid<P>
): WindowTile<P>[] {
	const size = pyramid.tile_size;
	const columns = chartColumns(spec.chart, spec.level);
	const rows = chartRows(spec.chart, spec.level);
	const tiles: WindowTile<P>[] = [];
	const lastY = Math.min(Math.floor((spec.y0 + spec.height - 1) / size), rows - 1);
	const lastX = Math.floor((spec.x0 + spec.width - 1) / size);
	for (let ty = Math.max(Math.floor(spec.y0 / size), 0); ty <= lastY; ty++) {
		for (let tx = Math.floor(spec.x0 / size); tx <= lastX; tx++) {
			if (spec.chart !== MAP && (tx < 0 || tx >= columns)) continue;
			const x = ((tx % columns) + columns) % columns;
			const patch =
				spec.level > pyramid.max_level
					? patchOfTile(pyramid.patches, spec.level, x, ty)
					: undefined;
			if (spec.level > pyramid.max_level && !patch) continue;
			tiles.push({
				cap: CHART_FOLDER[spec.chart],
				level: spec.level,
				x,
				y: ty,
				dx: tx * size - spec.x0,
				dy: ty * size - spec.y0,
				patch
			});
		}
	}
	const midX = spec.width / 2 - size / 2;
	const midY = spec.height / 2 - size / 2;
	const off = (tile: WindowTile<P>) => Math.hypot(tile.dx - midX, tile.dy - midY);
	return tiles.sort((a, b) => off(a) - off(b));
}

/**
 * Whether `held` has all the pixels that the frame of `spec` shows. On the
 * map, the two can count their columns from different turns of the globe.
 */
export function covers(held: WindowSpec, spec: WindowSpec, tileSize: number): boolean {
	if (held.chart !== spec.chart || held.level !== spec.level) return false;
	let turn = 0;
	if (spec.chart === MAP) {
		const chartWidth = chartColumns(MAP, spec.level) * tileSize;
		turn = chartWidth * Math.round((spec.inner[0] - held.x0) / chartWidth);
	}
	return (
		held.x0 + turn <= spec.inner[0] &&
		held.x0 + turn + held.width > spec.inner[2] &&
		held.y0 <= spec.inner[1] &&
		held.y0 + held.height > spec.inner[3]
	);
}
