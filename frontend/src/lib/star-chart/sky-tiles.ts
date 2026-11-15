/**
 * Which tiles of the star map a chart reads: pure geometry, kept apart from
 * the pictures so it can be tested.
 *
 * The star map is a tile pyramid (docs/export-format/tiles.md, "Star map").
 * Its east longitude is minus the right ascension, so the plan of a flat map
 * serves it as it is.
 */

import { chartFraction, levelForStep, planWindows, stepOfLevel } from '$lib/flatmap/tile-plan';
import type { Vec3 } from '$lib/math/travel/vec3';
import { CHART_FOLDER, MAP, chartColumns, chartRows, type Chart } from '$lib/scene/lod/tile-window';
import { centreScaleDeg, directionAt, project, type ChartFrame } from './frame';
import { PEAK_SHARE, tapsPerSide } from './sky';

const DEG = Math.PI / 180;

/** Tiles of one paint, at most: 64 MB as pixels. A frame that needs more
 *  reads a coarser level. */
export const MAX_TILES = 16;

/** Taps along one side of a pixel, at most. */
export const MAX_TAPS = 6;

/** A chart whose pixels match a level under this one reads the next level.
 *  The coarse levels hold a mean, which has lost the stars of a wide chart. */
const WIDE_UNDER_LEVEL = 2;

/** The peak share at a level that matches the picture. More makes salt of
 *  the faint stars of the Milky Way. */
export const MATCHED_PEAK_SHARE = 0.3;

/** Places of the frame where the size of a pixel on the chart is measured. */
const TAP_GRID = 5;

/** What a chart reads of the `skybox.tiles` block. */
export interface SkyPyramid {
	id: string;
	tile_size: number;
	max_level: number;
	version: string;
	/** `light = (byte / 255) ^ light_gamma`. */
	light_gamma: number;
}

export interface SkyTile {
	cap: (typeof CHART_FOLDER)[number];
	level: number;
	x: number;
	y: number;
}

/** The tiles of one paint: a grid of whole tiles of one level of one chart. */
export interface SkyPlan {
	chart: Chart;
	level: number;
	/** North-west tile of the grid. On the map, a column past the east edge
	 *  is the first one again. */
	column0: number;
	row0: number;
	columns: number;
	rows: number;
	/** Row by row from the north-west. */
	tiles: SkyTile[];
	/** Taps across and down one pixel of the picture: one per tile pixel. */
	taps: [across: number, down: number];
	/** How much of its brightest tap a pixel keeps over its mean. */
	peakShare: number;
}

/** A direction as a place of the pyramid: east longitude and latitude, degrees. */
export function skyPlace([x, y, z]: Vec3): [lon: number, lat: number] {
	return [-Math.atan2(y, x) / DEG, Math.asin(Math.max(-1, Math.min(1, z))) / DEG];
}

/** A direction in pixels of `level` of `chart`, from its north-west corner. */
export function skyPixel(
	chart: Chart,
	level: number,
	tileSize: number,
	direction: Vec3
): [x: number, y: number] {
	const [fx, fy] = chartFraction(chart, ...skyPlace(direction));
	return [fx * chartColumns(chart, level) * tileSize, fy * chartRows(chart, level) * tileSize];
}

function inFrame(frame: ChartFrame, direction: Vec3): boolean {
	// The point opposite the centre is in no frame.
	if (
		direction[0] * frame.forward[0] +
			direction[1] * frame.forward[1] +
			direction[2] * frame.forward[2] <
		-0.99
	)
		return false;
	const [x, y] = project(frame, direction);
	return x >= 0 && y >= 0 && x <= frame.width && y <= frame.height;
}

/** Tile pixels along one pixel of the picture, across and down, at the place
 *  of the frame where they are the most. */
function pixelsPerPixel(
	frame: ChartFrame,
	width: number,
	height: number,
	chart: Chart,
	level: number,
	tileSize: number
): [number, number] {
	const chartWidth = chartColumns(chart, level) * tileSize;
	const span = (a: [number, number], b: [number, number]): number => {
		let dx = Math.abs(b[0] - a[0]);
		// The two ends can be on the two sides of the map's edge.
		if (chart === MAP) dx = Math.min(dx, chartWidth - dx);
		return Math.hypot(dx, b[1] - a[1]);
	};
	let across = 0;
	let down = 0;
	for (let j = 0; j < TAP_GRID; j++) {
		for (let i = 0; i < TAP_GRID; i++) {
			const fx = (i + 0.5) / TAP_GRID;
			const fy = (j + 0.5) / TAP_GRID;
			const at = (dx: number, dy: number) =>
				skyPixel(chart, level, tileSize, directionAt(frame, fx + dx / width, fy + dy / height));
			across = Math.max(across, span(at(-0.5, 0), at(0.5, 0)));
			down = Math.max(down, span(at(0, -0.5), at(0, 0.5)));
		}
	}
	return [across, down];
}

/**
 * Where tile column `column` of a level is in a grid that starts at column
 * `first`. The map has no east edge, so the grid can start east of the column.
 * The shader has the same sum: `%` of a negative number is undefined there.
 * `column` is from one west of the level to one east of it.
 */
export function gridColumn(column: number, first: number, levelColumns: number): number {
	return (column - first + levelColumns) % levelColumns;
}

/**
 * The peak share for a pixel that holds `pixels` tile pixels. It grows from 3
 * tile pixels to 8: a pixel of many tile pixels loses its stars to the mean.
 */
export function peakShare(pixels: number): number {
	const ramp = Math.min(Math.max(Math.log2(pixels / 3) / Math.log2(8 / 3), 0), 1);
	return MATCHED_PEAK_SHARE + (PEAK_SHARE - MATCHED_PEAK_SHARE) * ramp;
}

/**
 * The tiles that paint `frame` as a picture of `width` pixels. The level is
 * the first one whose pixels are as small as those of the picture, or the
 * finest of the pyramid. A wide chart reads one level more. The chart is the
 * map, or a cap for a frame near a pole, by the rule of the flat maps.
 */
export function planSky(
	pyramid: SkyPyramid,
	frame: ChartFrame,
	width: number,
	height: number
): SkyPlan | null {
	const size = pyramid.tile_size;
	const sample = {
		place: (fx: number, fy: number) => skyPlace(directionAt(frame, fx, fy)),
		north: inFrame(frame, [0, 0, 1]),
		south: inFrame(frame, [0, 0, -1])
	};
	const coarsest = stepOfLevel(0, size);
	const matched = Math.max(
		levelForStep((centreScaleDeg(frame) * DEG * frame.width) / width, size),
		0
	);
	let step = stepOfLevel(matched < WIDE_UNDER_LEVEL ? matched + 1 : matched, size);
	for (;;) {
		const [spec] = planWindows(pyramid, { ...sample, step }, 0, false);
		if (!spec) return null;
		const { chart, level } = spec;
		const levelColumns = chartColumns(chart, level);
		const first = Math.floor(spec.x0 / size);
		const last = Math.floor((spec.x0 + spec.width - 1) / size);
		const column0 = chart === MAP ? first : Math.max(first, 0);
		const columns =
			chart === MAP
				? Math.min(last - first + 1, levelColumns)
				: Math.min(last, levelColumns - 1) - column0 + 1;
		const row0 = Math.max(Math.floor(spec.y0 / size), 0);
		const rows =
			Math.min(Math.floor((spec.y0 + spec.height - 1) / size), chartRows(chart, level) - 1) -
			row0 +
			1;
		if (columns * rows > MAX_TILES && step < coarsest) {
			step = Math.min(step * 2, coarsest);
			continue;
		}
		const tiles: SkyTile[] = [];
		for (let row = 0; row < rows; row++) {
			for (let column = 0; column < columns; column++) {
				tiles.push({
					cap: CHART_FOLDER[chart],
					level,
					x: (((column0 + column) % levelColumns) + levelColumns) % levelColumns,
					y: row0 + row
				});
			}
		}
		const [across, down] = pixelsPerPixel(frame, width, height, chart, level, size);
		return {
			chart,
			level,
			column0: ((column0 % levelColumns) + levelColumns) % levelColumns,
			row0,
			columns,
			rows,
			tiles,
			taps: [tapsPerSide(across, MAX_TAPS), tapsPerSide(down, MAX_TAPS)],
			peakShare: peakShare(across * down)
		};
	}
}
