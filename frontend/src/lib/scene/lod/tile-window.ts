/**
 * Where a body's tile windows sit: pure geometry of the tile grids
 * (docs/export-format/tiles.md), kept apart from the textures so it can be
 * tested.
 *
 * A body has three charts: the equirectangular map, and a polar stereographic
 * cap over each pole, where the map's columns close in to nothing. A window is
 * a block of tiles of one level of one chart, around the point under the
 * camera. Its texture is addressed like a torus: a tile always lands in the
 * slot its own column and row pick, so moving the window by one tile reloads
 * one line of slots and leaves the rest where they are.
 */

/** Tiles along each side of a window. */
export const WINDOW_TILES = 4;

export const MAP = 0;
export const NORTH = 1;
export const SOUTH = 2;
export type Chart = typeof MAP | typeof NORTH | typeof SOUTH;

/** Folder of each chart's tiles inside a pyramid. */
export const CHART_FOLDER = ['', 'north', 'south'] as const;

/** First level with a window. The whole-globe tier that stays under the
 *  windows holds the level below it, and a cap of this level is one window. */
export const FIRST_TILE_LEVEL = 3;

/** How far, in tiles, the camera may stray from a window's centre before the
 *  window follows. Below half a tile a hover on a tile edge would reload a
 *  line of tiles each way it drifts. */
const HOLD_TILES = 0.75;

const BASE_WIDTH_PX = 2048;

/** A cap's sides touch latitude 45°: the tangent of half that colatitude. */
export const CAP_EDGE = Math.SQRT2 - 1;

/**
 * Latitudes where the camera's chart changes, towards a pole and back. At 60°
 * a map window is half as wide on the ground as it is tall, and a cap window
 * of all but the two coarsest levels still fits inside its cap. The gap keeps
 * a camera near the line on one chart.
 */
const CAP_ENTER_DEG = 62;
const CAP_LEAVE_DEG = 58;

/** Latitude past which the coarsest level is held on both charts: each
 *  covers ground there that the other cannot. */
const BOTH_CHARTS_DEG = 45;

export interface WindowPlacement {
	chart: Chart;
	level: number;
	/** North-west tile of the window. On the map the column is taken modulo the level's. */
	tx0: number;
	ty0: number;
}

export function chartColumns(chart: Chart, level: number): number {
	return chart === MAP ? 2 << level : 1 << (level - 1);
}

export function chartRows(chart: Chart, level: number): number {
	return chart === MAP ? 1 << level : 1 << (level - 1);
}

/**
 * The level whose pixels match the screen's, straight under the camera.
 *
 * One screen pixel there spans `(dist − radius) / projScale` of ground, so the
 * whole map would need `2π·radius` over that in pixels. Not clamped below: a
 * caller compares it with what the whole-globe tiers already hold.
 */
export function neededLevel(
	radiusScene: number,
	dist: number,
	projScale: number,
	maxLevel: number
): number {
	const height = Math.max(dist - radiusScene, radiusScene * 1e-6);
	const widthPx = (2 * Math.PI * radiusScene * projScale) / height;
	return Math.min(Math.ceil(Math.log2(widthPx / BASE_WIDTH_PX)), maxLevel);
}

/**
 * Where the body-fixed unit direction `(x, y, z)` falls on `chart`, as
 * fractions of its width and height from its north-west corner. `y` is north
 * and `+x` the prime meridian, as on the sphere mesh. A cap takes ground past
 * its sides too, at fractions outside 0..1.
 */
export function chartPoint(
	chart: Chart,
	x: number,
	y: number,
	z: number
): { x: number; y: number } {
	if (chart === MAP) {
		const east = Math.atan2(z, -x) / (2 * Math.PI);
		return { x: east < 0 ? east + 1 : east, y: Math.acos(Math.min(Math.max(y, -1), 1)) / Math.PI };
	}
	// Seen from above its pole, the prime meridian to the right.
	const side = chart === NORTH ? 1 : -1;
	const scale = 0.5 / (CAP_EDGE * (1 + side * y));
	return { x: 0.5 + x * scale, y: 0.5 + side * z * scale };
}

/** The chart the camera's own windows are on, for a camera over the unit
 *  direction with north component `y`. `previous` is kept near the line. */
export function cameraChart(y: number, previous?: Chart): Chart {
	const cap = y >= 0 ? NORTH : SOUTH;
	const latitude = (Math.asin(Math.min(Math.abs(y), 1)) * 180) / Math.PI;
	return latitude > (previous === cap ? CAP_LEAVE_DEG : CAP_ENTER_DEG) ? cap : MAP;
}

/**
 * The windows a camera wants, finest first: one per level from `level` down,
 * as many as `count` allows, on the camera's chart. Where both charts reach
 * the camera and a place is left, the coarsest level comes on the other chart
 * too, last.
 */
export function windowChain(
	level: number,
	count: number,
	chart: Chart,
	y: number
): { chart: Chart; level: number }[] {
	const chain: { chart: Chart; level: number }[] = [];
	for (let z = level; z >= FIRST_TILE_LEVEL && chain.length < count; z--) {
		chain.push({ chart, level: z });
	}
	const reached = chain.length > 0 && chain[chain.length - 1].level === FIRST_TILE_LEVEL;
	const both = Math.abs(y) > Math.sin((BOTH_CHARTS_DEG * Math.PI) / 180);
	if (reached && both && chain.length < count) {
		const cap = y >= 0 ? NORTH : SOUTH;
		chain.push({ chart: chart === MAP ? cap : MAP, level: FIRST_TILE_LEVEL });
	}
	return chain;
}

/** First tile of a window along one axis of `count` tiles, for a camera `at`
 *  tiles from the axis's start. `kept` is the first tile it had. */
function placeAxis(at: number, count: number, wraps: boolean, kept?: number): number {
	const last = Math.max(count - WINDOW_TILES, 0);
	if (kept !== undefined) {
		let off = at - (kept + WINDOW_TILES / 2);
		if (wraps) off -= count * Math.round(off / count);
		// At an end the window cannot centre on the camera; it is as close as it gets.
		const pinned = !wraps && ((kept === 0 && off < 0) || (kept === last && off > 0));
		if (pinned || Math.abs(off) <= HOLD_TILES) return kept;
	}
	const first = Math.round(at - WINDOW_TILES / 2);
	return wraps ? ((first % count) + count) % count : Math.min(Math.max(first, 0), last);
}

/**
 * A window of `level` of `chart` around the chart point `(x, y)`, as
 * `chartPoint` gives it. `previous` is kept while the point stays near its
 * middle.
 */
export function placeWindow(
	chart: Chart,
	level: number,
	x: number,
	y: number,
	previous?: WindowPlacement
): WindowPlacement {
	const columns = chartColumns(chart, level);
	const rows = chartRows(chart, level);
	const kept = previous?.chart === chart && previous.level === level ? previous : undefined;
	const tx0 = placeAxis(x * columns, columns, chart === MAP, kept?.tx0);
	const ty0 = placeAxis(y * rows, rows, false, kept?.ty0);
	if (kept && kept.tx0 === tx0 && kept.ty0 === ty0) return kept;
	return { chart, level, tx0, ty0 };
}

/** The tile of `placement` that lives in slot `(sx, sy)` of its texture. */
export function slotTile(
	placement: WindowPlacement,
	sx: number,
	sy: number
): { x: number; y: number } {
	const columns = chartColumns(placement.chart, placement.level);
	const dx = (((sx - placement.tx0) % WINDOW_TILES) + WINDOW_TILES) % WINDOW_TILES;
	const dy = (((sy - placement.ty0) % WINDOW_TILES) + WINDOW_TILES) % WINDOW_TILES;
	return { x: (placement.tx0 + dx) % columns, y: placement.ty0 + dy };
}
