/**
 * Heights for the vertices of a terrain grid, read from decoded height tiles.
 *
 * A vertex takes the pyramid level whose pixels are as wide as the grid's
 * cells around it: a finer level would pick one pixel out of many, and the
 * ground would look rougher than it is. Past latitude 60° it reads the cap of
 * its pole, where a fine band of the grid stays on a few tiles.
 *
 * A level past the pyramid's finest has tiles on the ground of a patch only.
 * A vertex beside the patch takes the finest level that has its ground.
 */

import {
	type Chart,
	MAP,
	NORTH,
	SOUTH,
	chartColumns,
	chartPoint,
	chartRows
} from '$lib/scene/lod/tile-window';
import type { GridAxis } from '$lib/scene/lod/terrain-grid';

/** sin of the latitude past which a vertex reads its pole's cap. */
const CAP_SIN = Math.sin((60 * Math.PI) / 180);

/** A decoded tile by its key: heights in 16-bit steps, north row first. */
export type TileLookup = (key: number) => Uint16Array | Float32Array | undefined;

/** Whether a tile is there to fetch. */
export type TileExists = (chart: Chart, level: number, x: number, y: number) => boolean;

// Room for level 16 of the map: 2^17 columns and 2^16 rows.
const KEY_COLUMNS = 2 ** 18;
const KEY_ROWS = 2 ** 17;
const KEY_LEVELS = 32;

export function tileKey(chart: Chart, level: number, x: number, y: number): number {
	return ((chart * KEY_LEVELS + level) * KEY_COLUMNS + x) * KEY_ROWS + y;
}

export function tileOfKey(key: number): { chart: Chart; level: number; x: number; y: number } {
	const y = key % KEY_ROWS;
	const x = Math.floor(key / KEY_ROWS) % KEY_COLUMNS;
	const head = Math.floor(key / (KEY_ROWS * KEY_COLUMNS));
	return { chart: Math.floor(head / KEY_LEVELS) as Chart, level: head % KEY_LEVELS, x, y };
}

/** The four pixels around a point of one level of one chart. */
interface Corner {
	chart: Chart;
	level: number;
	x0: number;
	x1: number;
	y0: number;
	y1: number;
	fx: number;
	fy: number;
}

const corner: Corner = { chart: MAP, level: 0, x0: 0, x1: 0, y0: 0, y1: 0, fx: 0, fy: 0 };

/** Where the body-fixed unit direction `(x, y, z)` falls at `level`, on the
 *  chart a vertex there reads. */
function locate(level: number, x: number, y: number, z: number, tileSize: number): Corner {
	// A cap starts at level 1.
	const chart = level < 1 || Math.abs(y) <= CAP_SIN ? MAP : y > 0 ? NORTH : SOUTH;
	const width = chartColumns(chart, level) * tileSize;
	const height = chartRows(chart, level) * tileSize;
	const at = chartPoint(chart, x, y, z);
	const px = at.x * width - 0.5;
	const py = at.y * height - 0.5;
	const x0 = Math.floor(px);
	const y0 = Math.floor(py);
	const clampX = (v: number) => Math.min(Math.max(v, 0), width - 1);
	const clampY = (v: number) => Math.min(Math.max(v, 0), height - 1);
	corner.chart = chart;
	corner.level = level;
	corner.fx = px - x0;
	corner.fy = py - y0;
	// The map goes round; a cap and the map's poles end.
	corner.x0 = chart === MAP ? (x0 + width) % width : clampX(x0);
	corner.x1 = chart === MAP ? (x0 + 1) % width : clampX(x0 + 1);
	corner.y0 = clampY(y0);
	corner.y1 = clampY(y0 + 1);
	return corner;
}

/** Call `visit` with each vertex of the grid: its index, the level its cell
 *  asks for, and its direction in the body's frame. */
function eachVertex(
	rows: GridAxis,
	columns: GridAxis,
	visit: (vertex: number, level: number, x: number, y: number, z: number) => void
): void {
	const sinPhi = Float64Array.from(columns.at, Math.sin);
	const cosPhi = Float64Array.from(columns.at, Math.cos);
	const cols = columns.at.length;
	for (let iy = 0; iy < rows.at.length; iy++) {
		const sinT = Math.sin(rows.at[iy]);
		const cosT = Math.cos(rows.at[iy]);
		for (let ix = 0; ix < cols; ix++) {
			const level = Math.min(rows.level[iy], columns.level[ix]);
			visit(iy * cols + ix, level, -cosPhi[ix] * sinT, cosT, sinPhi[ix] * sinT);
		}
	}
}

/**
 * Keys of the tiles a grid reads, the two of the coarsest level included:
 * they are what a vertex falls back to. `finest` is the finest level of the
 * pyramid itself. Past it, a vertex whose tiles do not all exist asks for
 * those of the level below, down to the pyramid's own.
 */
export function gridTiles(
	rows: GridAxis,
	columns: GridAxis,
	tileSize: number,
	finest = Infinity,
	exists: TileExists = () => true
): Set<number> {
	const keys = new Set<number>([tileKey(MAP, 0, 0, 0), tileKey(MAP, 0, 1, 0)]);
	eachVertex(rows, columns, (_vertex, asked, x, y, z) => {
		for (let level = asked; ; level--) {
			const at = locate(level, x, y, z, tileSize);
			const tx0 = Math.floor(at.x0 / tileSize);
			const tx1 = Math.floor(at.x1 / tileSize);
			const ty0 = Math.floor(at.y0 / tileSize);
			const ty1 = Math.floor(at.y1 / tileSize);
			if (
				level > finest &&
				!(
					exists(at.chart, level, tx0, ty0) &&
					exists(at.chart, level, tx1, ty0) &&
					exists(at.chart, level, tx0, ty1) &&
					exists(at.chart, level, tx1, ty1)
				)
			) {
				continue;
			}
			keys.add(tileKey(at.chart, level, tx0, ty0));
			if (tx1 !== tx0) keys.add(tileKey(at.chart, level, tx1, ty0));
			if (ty1 !== ty0) {
				keys.add(tileKey(at.chart, level, tx0, ty1));
				if (tx1 !== tx0) keys.add(tileKey(at.chart, level, tx1, ty1));
			}
			return;
		}
	});
	return keys;
}

/**
 * The height value (0..65535, filtered) at a direction, from `level` or the
 * finest level below it whose tiles are all there: a tile that failed, or the
 * ground beside a patch. Undefined when even the coarsest is missing.
 */
function sampleValue(
	lookup: TileLookup,
	level: number,
	x: number,
	y: number,
	z: number,
	tileSize: number
): number | undefined {
	for (let l = level; l >= 0; l--) {
		const at = locate(l, x, y, z, tileSize);
		const pixel = (px: number, py: number): number | undefined => {
			const tile = lookup(
				tileKey(at.chart, l, Math.floor(px / tileSize), Math.floor(py / tileSize))
			);
			return tile && tile[(py % tileSize) * tileSize + (px % tileSize)];
		};
		const a = pixel(at.x0, at.y0);
		const b = pixel(at.x1, at.y0);
		const c = pixel(at.x0, at.y1);
		const d = pixel(at.x1, at.y1);
		if (a === undefined || b === undefined || c === undefined || d === undefined) continue;
		const top = a + (b - a) * at.fx;
		const bottom = c + (d - c) * at.fx;
		return top + (bottom - top) * at.fy;
	}
	return undefined;
}

/**
 * Height of each vertex of the grid above its sphere, in km, row by row:
 * `biasKm + scaleKm · value / 65535`. Null when the coarsest level is missing.
 */
export function gridHeights(
	rows: GridAxis,
	columns: GridAxis,
	lookup: TileLookup,
	tileSize: number,
	scaleKm: number,
	biasKm: number
): Float32Array | null {
	const out = new Float32Array(rows.at.length * columns.at.length);
	let missing = false;
	eachVertex(rows, columns, (vertex, level, x, y, z) => {
		const value = sampleValue(lookup, level, x, y, z, tileSize);
		if (value === undefined) missing = true;
		else out[vertex] = biasKm + (scaleKm * value) / 65535;
	});
	return missing ? null : out;
}
