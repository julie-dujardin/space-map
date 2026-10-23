import { describe, expect, it } from 'vitest';
import { MAP, NORTH, SOUTH } from '$lib/scene/lod/tile-window';
import { createProjection, type ProjectionId, type ProjectionOptions } from './projection';
import {
	MAX_WINDOW_PIXELS,
	chartFraction,
	covers,
	finestLevelAt,
	levelForStep,
	planWindows,
	stepOfLevel,
	windowTiles,
	type FrameSample,
	type Pyramid,
	type WindowSpec
} from './tile-plan';
import { Viewport } from './view';

const WIDTH = 1200;
const HEIGHT = 800;
const SIZE = 1024;

/** A pyramid like that of Mars: ten levels, and a patch at Jezero. */
const MARS: Pyramid = {
	tile_size: SIZE,
	max_level: 10,
	patches: [{ max_level: 16, x: [93591, 93783], y: [25970, 26165] }]
};
const JEZERO = { lon: 77.45, lat: 18.44 };

/** The frame of a map that looks at a place, with `metres` of Mars for each pixel. */
function frame(
	id: ProjectionId,
	lon: number,
	lat: number,
	metres: number,
	options: ProjectionOptions = {}
): FrameSample {
	const azimuthal = id === 'orthographic' || id === 'stereographic';
	const projection = createProjection(
		id,
		azimuthal ? { centerLon: lon, centerLat: lat, ...options } : options
	);
	const step = metres / 3_389_500;
	const at = (zoom: number) => {
		const plane = azimuthal ? [0, 0] : projection.forward(lon, lat)!;
		return new Viewport(projection, WIDTH, HEIGHT, { zoom, centerX: plane[0], centerY: plane[1] });
	};
	// The step of a frame is in proportion to 1 / zoom.
	const one = at(1000);
	const a = one.unproject(WIDTH / 2, HEIGHT / 2)!;
	const b = one.unproject(WIDTH / 2, HEIGHT / 2 + 1)!;
	const viewport = at((1000 * Math.abs(a[1] - b[1]) * Math.PI) / 180 / step);
	const pole = (poleLat: number) => {
		const p = azimuthal ? viewport.project(0, poleLat) : null;
		return !!p && p[0] >= 0 && p[0] <= WIDTH && p[1] >= 0 && p[1] <= HEIGHT;
	};
	return {
		place: (fx, fy) => viewport.unproject(fx * WIDTH, fy * HEIGHT),
		step,
		north: pole(90),
		south: pole(-90)
	};
}

/** The level whose pixels match those of a frame. */
describe('levelForStep', () => {
	it('gives the first level that is drawn at 1.25 times its size or less', () => {
		const step = stepOfLevel(6, SIZE);
		expect(levelForStep(step, SIZE)).toBe(6);
		expect(levelForStep(step / 1.2, SIZE)).toBe(6);
		expect(levelForStep(step / 1.3, SIZE)).toBe(7);
		expect(levelForStep(step * 1.5, SIZE)).toBe(6);
		expect(levelForStep(step * 1.7, SIZE)).toBe(5);
	});
});

/** A place on each chart, as the tile format states it. */
describe('chartFraction', () => {
	it('puts 180°W at the left edge of the map and the north pole at its top', () => {
		expect(chartFraction(MAP, -180, 90)).toEqual([0, 0]);
		expect(chartFraction(MAP, 0, 0)).toEqual([0.5, 0.5]);
		expect(chartFraction(MAP, 90, -45)).toEqual([0.75, 0.75]);
	});

	it('puts the pole at the middle of its cap, and latitude 45° at the middle of a side', () => {
		const close = ([x, y]: [number, number], ex: number, ey: number) => {
			expect(x).toBeCloseTo(ex, 12);
			expect(y).toBeCloseTo(ey, 12);
		};
		close(chartFraction(NORTH, 0, 90), 0.5, 0.5);
		close(chartFraction(SOUTH, 123, -90), 0.5, 0.5);
		// The prime meridian is to the right. East is counter-clockwise on the
		// north cap and clockwise on the south cap.
		close(chartFraction(NORTH, 0, 45), 1, 0.5);
		close(chartFraction(NORTH, 90, 45), 0.5, 0);
		close(chartFraction(SOUTH, 0, -45), 1, 0.5);
		close(chartFraction(SOUTH, 90, -45), 0.5, 1);
	});
});

/** The finest level with a tile at a place. */
describe('finestLevelAt', () => {
	it('is the finest level of the pyramid away from a patch', () => {
		expect(finestLevelAt(MARS, 0, 0)).toBe(10);
	});

	it('is that of a patch over the place', () => {
		expect(finestLevelAt(MARS, JEZERO.lon, JEZERO.lat)).toBe(16);
	});

	it('takes a longitude past ±180°', () => {
		expect(finestLevelAt(MARS, JEZERO.lon - 360, JEZERO.lat)).toBe(16);
		expect(finestLevelAt(MARS, JEZERO.lon + 360, JEZERO.lat)).toBe(16);
	});
});

/** The windows of a frame. */
describe('planWindows', () => {
	it('gives none while the whole-body picture holds enough', () => {
		expect(planWindows(MARS, frame('equirectangular', 0, 0, 20_000), 3)).toEqual([]);
	});

	it('gives one window of the level that matches the frame', () => {
		const [spec, ...rest] = planWindows(MARS, frame('equirectangular', 30, -20, 100), 3);
		expect(rest).toEqual([]);
		expect(spec.chart).toBe(MAP);
		// Level 7 has pixels of 81 m and level 6 of 162 m.
		expect(spec.level).toBe(7);
	});

	it('holds the frame, and a margin around it', () => {
		const [spec] = planWindows(MARS, frame('equirectangular', 30, -20, 100), 3);
		const pixel = stepOfLevel(7, SIZE) * 3_389_500;
		const [x, y] = chartFraction(MAP, 30, -20);
		const across = 2 * SIZE * 2 ** 7;
		expect(spec.inner[0]).toBeLessThanOrEqual(x * across - (WIDTH / 2) * (100 / pixel));
		expect(spec.inner[2]).toBeGreaterThanOrEqual(x * across + (WIDTH / 2) * (100 / pixel) - 1);
		expect(spec.inner[1]).toBeLessThanOrEqual(y * SIZE * 2 ** 7 - (HEIGHT / 2) * (100 / pixel));
		expect(spec.x0).toBeLessThan(spec.inner[0]);
		expect(spec.x0 + spec.width).toBeGreaterThan(spec.inner[2] + 1);
	});

	it('holds no margin for a frame that stays in place', () => {
		const [spec] = planWindows(MARS, frame('equirectangular', 30, -20, 100), 3, false);
		expect(spec.x0).toBe(spec.inner[0]);
		expect(spec.x0 + spec.width).toBe(spec.inner[2] + 1);
		expect(spec.y0 + spec.height).toBe(spec.inner[3] + 1);
	});

	it('stops at the finest level of the pyramid away from a patch', () => {
		const [spec, ...rest] = planWindows(MARS, frame('equirectangular', 0, 0, 0.5), 3);
		expect(rest).toEqual([]);
		expect(spec.level).toBe(10);
	});

	it('goes past it over a patch, with a window of the pyramid for the ground around', () => {
		const specs = planWindows(MARS, frame('orthographic', JEZERO.lon, JEZERO.lat, 0.5), 2);
		expect(specs.map((spec) => spec.level)).toEqual([15, 10]);
		expect(specs[0].chart).toBe(MAP);
	});

	it('continues across the ±180° meridian', () => {
		const [spec] = planWindows(MARS, frame('equirectangular', 179.99, 0, 100), 3);
		const across = 2 * SIZE * 2 ** spec.level;
		expect(spec.x0).toBeLessThan(across);
		expect(spec.x0 + spec.width).toBeGreaterThan(across);
	});

	it('uses a cap near a pole, where the map needs many more pixels', () => {
		const [north] = planWindows(MARS, frame('orthographic', 20, 80, 100), 2);
		expect(north.chart).toBe(NORTH);
		const [south] = planWindows(MARS, frame('orthographic', 20, -80, 100), 2);
		expect(south.chart).toBe(SOUTH);
		const [pole] = planWindows(MARS, frame('orthographic', 0, 90, 100), 2);
		expect(pole.chart).toBe(NORTH);
		expect(pole.level).toBe(7);
	});

	it('stays on the map near the equator', () => {
		const [spec] = planWindows(MARS, frame('orthographic', 20, 10, 100), 2);
		expect(spec.chart).toBe(MAP);
	});

	it('takes a coarser level when the frame needs too many pixels', () => {
		// The whole globe is in the frame, and the step at its middle is small.
		const whole: FrameSample = {
			place: (fx, fy) => [-180 + 360 * fx, 90 - 180 * fy],
			step: stepOfLevel(8, SIZE)
		};
		const [spec] = planWindows(MARS, whole, 0);
		expect(spec.level).toBeLessThan(8);
		expect(spec.width * spec.height).toBeLessThanOrEqual(MAX_WINDOW_PIXELS);
	});

	it('gives none when the middle of the frame is off the world', () => {
		const off: FrameSample = { place: () => null, step: stepOfLevel(8, SIZE) };
		expect(planWindows(MARS, off, 2)).toEqual([]);
	});
});

/** A patch on the north cap, around Phoenix's landing site. */
describe('a patch on a cap', () => {
	const PHOENIX = { lon: -125.75, lat: 68.22 };
	const [u, v] = chartFraction(NORTH, PHOENIX.lon, PHOENIX.lat);
	const columns = 2 ** 15;
	const x = Math.floor(u * columns);
	const y = Math.floor(v * columns);
	const polar: Pyramid = {
		tile_size: SIZE,
		max_level: 10,
		patches: [{ cap: 'north', max_level: 16, x: [x - 30, x + 30], y: [y - 30, y + 30] }]
	};

	it('is the finest level over its place', () => {
		expect(finestLevelAt(polar, PHOENIX.lon, PHOENIX.lat)).toBe(16);
		expect(finestLevelAt(polar, PHOENIX.lon + 10, PHOENIX.lat)).toBe(10);
	});

	it('gets a window of its cap, with one of the pyramid for the ground around', () => {
		const specs = planWindows(polar, frame('orthographic', PHOENIX.lon, PHOENIX.lat, 0.5), 2);
		expect(specs.map((spec) => [spec.chart, spec.level])).toEqual([
			[NORTH, 15],
			[NORTH, 10]
		]);
		const tiles = windowTiles(specs[0], polar);
		expect(tiles.length).toBeGreaterThan(0);
		expect(tiles.every((tile) => tile.cap === 'north' && tile.patch === polar.patches![0])).toBe(
			true
		);
	});
});

/** The tiles of a window. */
describe('windowTiles', () => {
	it('gives each tile once, with its place in the window', () => {
		const tiles = windowTiles(
			{ chart: MAP, level: 3, x0: 1000, y0: 1100, width: 1100, height: 100, inner: [0, 0, 0, 0] },
			MARS
		);
		expect(tiles.map((tile) => [tile.x, tile.y, tile.dx, tile.dy]).sort()).toEqual([
			[0, 1, -1000, -76],
			[1, 1, 24, -76],
			[2, 1, 1048, -76]
		]);
		expect(tiles.every((tile) => tile.cap === '' && tile.level === 3)).toBe(true);
	});

	it('wraps a column past the ±180° meridian', () => {
		const tiles = windowTiles(
			{ chart: MAP, level: 3, x0: -500, y0: 0, width: 1000, height: 10, inner: [0, 0, 0, 0] },
			MARS
		);
		expect(tiles.map((tile) => [tile.x, tile.dx]).sort()).toEqual([
			[0, 500],
			[15, -524]
		]);
	});

	it('names the folder of a cap', () => {
		const [tile] = windowTiles(
			{ chart: SOUTH, level: 3, x0: 10, y0: 10, width: 10, height: 10, inner: [0, 0, 0, 0] },
			MARS
		);
		expect(tile.cap).toBe('south');
	});

	it('gives only the tiles of a patch past the finest level of the pyramid', () => {
		const patch = MARS.patches![0];
		const x0 = patch.x[0] * SIZE - 2 * SIZE;
		const tiles = windowTiles(
			{
				chart: MAP,
				level: 16,
				x0,
				y0: patch.y[0] * SIZE,
				width: 4 * SIZE,
				height: SIZE,
				inner: [0, 0, 0, 0]
			},
			MARS
		);
		expect(tiles.map((tile) => tile.x).sort()).toEqual([patch.x[0], patch.x[0] + 1]);
		expect(tiles.every((tile) => tile.patch === patch)).toBe(true);
	});
});

/** Whether a held window still serves a frame. */
describe('covers', () => {
	const held: WindowSpec = {
		chart: MAP,
		level: 3,
		x0: 100,
		y0: 100,
		width: 1000,
		height: 500,
		inner: [0, 0, 0, 0]
	};
	const need = (x0: number, y0: number, x1: number, y1: number): WindowSpec => ({
		...held,
		inner: [x0, y0, x1, y1]
	});

	it('is true when the frame is inside the window', () => {
		expect(covers(held, need(100, 100, 1099, 599), SIZE)).toBe(true);
		expect(covers(held, need(100, 100, 1100, 599), SIZE)).toBe(false);
		expect(covers(held, need(99, 100, 500, 599), SIZE)).toBe(false);
	});

	it('is false for another level or chart', () => {
		expect(covers(held, { ...need(200, 200, 300, 300), level: 4 }, SIZE)).toBe(false);
		expect(covers(held, { ...need(200, 200, 300, 300), chart: NORTH }, SIZE)).toBe(false);
	});

	it('is true for a frame that counts its columns from another turn of the globe', () => {
		const turn = 2 * SIZE * 2 ** 3;
		expect(covers(held, need(200 - turn, 200, 300 - turn, 300), SIZE)).toBe(true);
	});
});
