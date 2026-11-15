import { describe, expect, it } from 'vitest';
import type { Vec3 } from '$lib/math/travel/vec3';
import { MAP, NORTH, SOUTH } from '$lib/scene/lod/tile-window';
import { stepOfLevel } from '$lib/flatmap/tile-plan';
import { figureAspect, fillFrame, fitFrame } from './frame';
import { PAINT_RATIO, PEAK_SHARE, paintRatio } from './sky';
import {
	MATCHED_PEAK_SHARE,
	MAX_TILES,
	MIN_TILES,
	gridColumn,
	peakShare,
	planSky,
	planYields,
	skyPixel,
	tileBudget,
	type SkyPyramid
} from './sky-tiles';

const DEG = Math.PI / 180;
const PYRAMID: SkyPyramid = {
	id: 'stars',
	tile_size: 1024,
	max_level: 5,
	version: 'v',
	light_gamma: 4
};

function direction(raDeg: number, decDeg: number): Vec3 {
	const ra = raDeg * DEG;
	const dec = decDeg * DEG;
	return [Math.cos(dec) * Math.cos(ra), Math.cos(dec) * Math.sin(ra), Math.sin(dec)];
}

/** A square frame of `fieldDeg` around a place, `pixels` on a side. */
function frameAt(raDeg: number, decDeg: number, fieldDeg: number, pixels: number) {
	return fitFrame([direction(raDeg, decDeg)], {
		width: pixels,
		height: pixels,
		minFieldDeg: fieldDeg
	});
}

describe('skyPixel', () => {
	// The formulas of the pyramid, as its build states them.
	it('puts a direction on the map with east to the left', () => {
		for (const [ra, dec] of [
			[83.8, -1.2],
			[0.5, 10],
			[359.5, 10],
			[200, -60]
		]) {
			const [x, y, z] = direction(ra, dec);
			const u = (((0.5 - Math.atan2(y, x) / (2 * Math.PI)) % 1) + 1) % 1;
			const v = Math.acos(z) / Math.PI;
			const [px, py] = skyPixel(MAP, 5, 1024, [x, y, z]);
			expect(px).toBeCloseTo(u * 65536, 6);
			expect(py).toBeCloseTo(v * 32768, 6);
		}
	});

	it('puts a direction on each cap', () => {
		for (const [ra, dec] of [
			[37.95, 89.26],
			[222.7, 74.2],
			[186.6, -63.1],
			[10, -50]
		]) {
			const alpha = ra * DEG;
			const r = Math.tan(((90 - Math.abs(dec)) * DEG) / 2) / Math.tan(22.5 * DEG);
			const u = (1 + r * Math.cos(alpha)) / 2;
			const v = (1 + (dec > 0 ? 1 : -1) * r * Math.sin(alpha)) / 2;
			const [px, py] = skyPixel(dec > 0 ? NORTH : SOUTH, 5, 1024, direction(ra, dec));
			expect(px).toBeCloseTo(u * 16384, 6);
			expect(py).toBeCloseTo(v * 16384, 6);
		}
	});

	it('has RA 0h in the middle of the map and 12h at its edges', () => {
		expect(skyPixel(MAP, 0, 1024, direction(0, 0))[0]).toBeCloseTo(1024, 6);
		expect(skyPixel(MAP, 0, 1024, direction(179.9, 0))[0]).toBeLessThan(1);
		expect(skyPixel(MAP, 0, 1024, direction(180.1, 0))[0]).toBeGreaterThan(2047);
	});
});

describe('planSky', () => {
	it('reads the level whose pixels match the picture', () => {
		// 20 degrees on 720 pixels: 36 px per degree. Level 3 holds 45.5.
		const plan = planSky(PYRAMID, frameAt(80, 0, 20, 360), 720, 720)!;
		expect(plan.chart).toBe(MAP);
		expect(plan.level).toBe(3);
		// The same frame as a picture of half the size reads the level under it.
		expect(planSky(PYRAMID, frameAt(80, 0, 20, 360), 360, 360)!.level).toBe(2);
	});

	it('stops at the finest level', () => {
		const plan = planSky(PYRAMID, frameAt(80, 0, 1, 360), 720, 720)!;
		expect(plan.level).toBe(5);
		expect(plan.taps).toEqual([1, 1]);
	});

	it('reads one level more for a wide chart, and keeps the peaks', () => {
		const plan = planSky(PYRAMID, frameAt(150, -15, 100, 150), 300, 300)!;
		expect(plan.level).toBe(1);
		expect(plan.taps[0]).toBeGreaterThan(1);
		expect(plan.peakShare).toBeGreaterThan(MATCHED_PEAK_SHARE);
	});

	it('gives the tiles under the frame, row by row', () => {
		// Orion's belt at level 5: column 17, row 16.
		const plan = planSky(PYRAMID, frameAt(84.05, -1.2, 1, 360), 720, 720)!;
		expect(plan.tiles).toHaveLength(plan.columns * plan.rows);
		expect(plan.tiles).toContainEqual({ cap: '', level: 5, x: 17, y: 16 });
		expect(plan.tiles[0]).toEqual({ cap: '', level: 5, x: plan.column0, y: plan.row0 });
	});

	it('covers a frame across RA 0h with the columns in the middle of the map', () => {
		const plan = planSky(PYRAMID, frameAt(0, 10, 20, 360), 720, 720)!;
		const columns = new Set(plan.tiles.map(({ x }) => x));
		// Level 3 has 16 columns. RA 0h is between columns 7 and 8.
		expect(plan.level).toBe(3);
		expect(columns.has(7) && columns.has(8)).toBe(true);
	});

	it('covers a frame across RA 12h with the two edges of the map', () => {
		const plan = planSky(PYRAMID, frameAt(180, 10, 20, 360), 720, 720)!;
		expect(plan.tiles.map(({ x }) => x).slice(0, plan.columns)).toEqual([15, 0]);
		expect(plan.column0).toBe(15);
	});

	it('reads a cap near a pole', () => {
		const north = planSky(PYRAMID, frameAt(230, 78, 30, 360), 720, 720)!;
		expect(north.chart).toBe(NORTH);
		expect(north.tiles.every(({ cap }) => cap === 'north')).toBe(true);
		const south = planSky(PYRAMID, frameAt(187, -60, 10, 360), 720, 720)!;
		expect(south.chart).toBe(SOUTH);
		// The pole is the middle of a cap: Crux is in its tiles of RA 12h.
		const size = 1 << (south.level - 1);
		expect(south.tiles.every(({ x, y }) => x < size / 2 && y < size)).toBe(true);
	});

	it('reads the map for a frame that a cap does not hold', () => {
		expect(planSky(PYRAMID, frameAt(90, 40, 40, 360), 720, 720)!.chart).toBe(MAP);
	});

	it('reads a coarser level for a picture past its budget', () => {
		// 2420 px over 48 degrees near the pole match level 3, which is 16 tiles there.
		const frame = fitFrame([direction(240, 80)], { width: 1210, height: 900, minFieldDeg: 36 });
		expect(planSky(PYRAMID, frame, 2420, 1800)).toMatchObject({ chart: NORTH, level: 3 });
		const small = planSky(PYRAMID, frame, 1210, 900)!;
		expect(small.tiles.length).toBeLessThanOrEqual(tileBudget(1210, 900, 1024));
	});

	it('never asks for more tiles than the limit', () => {
		for (const [ra, dec, field, pixels] of [
			[0, 89, 170, 2000],
			[180, 0, 120, 4000],
			[100, -45, 60, 6000],
			[10, 60, 8, 8000]
		]) {
			const plan = planSky(PYRAMID, frameAt(ra, dec, field, pixels / 2), pixels, pixels)!;
			expect(plan.tiles.length).toBeLessThanOrEqual(MAX_TILES);
			expect(plan.tiles.length).toBeGreaterThan(0);
		}
	});
});

describe('peakShare', () => {
	it('is small for a matched level and whole for a pixel of many tile pixels', () => {
		expect(peakShare(1)).toBe(MATCHED_PEAK_SHARE);
		expect(peakShare(2.5)).toBe(MATCHED_PEAK_SHARE);
		expect(peakShare(5)).toBeGreaterThan(MATCHED_PEAK_SHARE);
		expect(peakShare(30)).toBe(PEAK_SHARE);
	});
});

describe('gridColumn', () => {
	it('never takes the remainder of a negative number', () => {
		// The shader's `%` is undefined there, and JavaScript's gives a negative column.
		for (const columns of [2, 4, 64]) {
			for (let first = 0; first < columns; first++) {
				for (let column = -1; column <= columns; column++) {
					expect(column - first + columns).toBeGreaterThanOrEqual(0);
					const slot = gridColumn(column, first, columns);
					expect(slot).toBeGreaterThanOrEqual(0);
					expect((first + slot) % columns).toBe((column + columns) % columns);
				}
			}
		}
	});

	it('holds a grid across RA 12h in rising columns', () => {
		const plan = planSky(PYRAMID, frameAt(180, 0, 20, 400), 800, 800)!;
		const columns = plan.tiles.length / plan.rows;
		const row = plan.tiles.slice(0, columns).map(({ x }) => x);
		// The grid starts near the east edge, so its last columns are west of its first.
		expect(row.at(-1)).toBeLessThan(plan.column0);
		expect(row.map((x) => gridColumn(x, plan.column0, 2 ** plan.level * 2))).toEqual(
			row.map((_, i) => i)
		);
	});
});

describe('tileBudget', () => {
	it('gives a larger picture more tiles, within the bounds', () => {
		expect(tileBudget(714, 714, 1024)).toBe(MIN_TILES);
		expect(tileBudget(780, 1688, 1024)).toBeGreaterThan(MIN_TILES);
		expect(tileBudget(2420, 1800, 1024)).toBe(MAX_TILES);
	});
});

// Figures as RA and declination of their stars, degrees.
const FIGURES: Record<string, [number, number][]> = {
	cygnus: [
		[310.4, 45.3],
		[305.6, 40.3],
		[311.6, 34.0],
		[292.7, 28.0],
		[296.2, 45.1],
		[292.4, 51.7],
		[289.3, 53.4],
		[303.9, 47.7],
		[314.3, 41.2],
		[318.2, 30.2]
	],
	scorpius: [
		[241.4, -19.8],
		[240.1, -22.6],
		[239.7, -26.1],
		[245.3, -25.6],
		[247.4, -26.4],
		[249.0, -28.2],
		[252.5, -34.3],
		[253.0, -38.0],
		[253.6, -42.4],
		[258.0, -43.2],
		[264.3, -43.0],
		[266.9, -40.1],
		[265.6, -39.0],
		[267.5, -37.0],
		[243.0, -19.5]
	],
	centaurus: [
		[190.4, -49.0],
		[205.0, -53.5],
		[211.0, -60.4],
		[219.9, -60.8],
		[208.9, -47.3],
		[209.7, -44.8],
		[218.9, -42.2],
		[215.1, -37.9],
		[170.3, -54.5],
		[182.1, -50.7],
		[172.9, -59.4],
		[202.8, -39.4],
		[190.0, -40.0],
		[224.8, -42.1]
	],
	ursaMajor: [
		[178.5, 53.7],
		[176.5, 47.8],
		[167.4, 44.5],
		[155.6, 41.5],
		[169.6, 33.1],
		[169.5, 31.5],
		[183.9, 57.0],
		[165.9, 61.8],
		[193.5, 56.0],
		[201.0, 54.9],
		[206.9, 49.3],
		[142.9, 63.1],
		[127.6, 60.7],
		[134.8, 48.0]
	],
	single: [[56.6, 24.1]]
};

/** The level, or the cube of 4096 px a face, of a chart as the drawer's hero
 *  paints it and as the viewer paints it. */
function levels(figure: string, viewer: [number, number], deviceRatio: number) {
	const points = FIGURES[figure].map(([ra, dec]) => direction(ra, dec));
	const cube = Math.PI / 2 / 4096;
	const read = (frame: ReturnType<typeof fitFrame>, ratio: number) => {
		const width = Math.round(frame.width * ratio);
		const plan = planSky(PYRAMID, frame, width, Math.round(frame.height * ratio))!;
		expect(plan.tiles.length).toBeLessThanOrEqual(tileBudget(width, frame.height * ratio, 1024));
		return planYields(plan, cube, 1024) ? 'cube' : plan.level;
	};
	const aspect = figureAspect(points, 1, 1.6);
	const hero = fitFrame(points, { width: 357, height: Math.round(357 / aspect) });
	const [width, height] = viewer;
	const fill = fillFrame(points, { width, height, clear: [16, 72] });
	return [read(hero, PAINT_RATIO), read(fill, paintRatio(width, height, deviceRatio))];
}

describe('the maximised chart', () => {
	// The cube of 4096 px a face holds the pixels of level 3.
	it.each([
		['cygnus', [1210, 900], 2, [2, 2]],
		['scorpius', [1210, 900], 2, [2, 3]],
		['centaurus', [1210, 900], 2, [2, 2]],
		['centaurus', [1210, 900], 1, [2, 2]],
		['ursaMajor', [390, 844], 3, [2, 'cube']],
		['centaurus', [390, 844], 3, [2, 'cube']],
		['single', [1210, 900], 2, [4, 5]]
	] as const)('of %s in %j at ratio %d reads %j', (figure, viewer, ratio, expected) => {
		expect(levels(figure, [...viewer], ratio)).toEqual(expected);
	});
});

describe('planYields', () => {
	const frame = fitFrame([direction(240, 80)], { width: 1210, height: 900, minFieldDeg: 36 });

	it('keeps a plan at the level that the picture wants', () => {
		const plan = planSky(PYRAMID, frame, 1210, 900)!;
		expect(plan.short).toBe(false);
		expect(planYields(plan, stepOfLevel(plan.level + 3, 1024), 1024)).toBe(false);
	});

	it('gives a plan that the budget made coarse to a sky two levels finer', () => {
		const plan = { ...planSky(PYRAMID, frame, 1210, 900)!, short: true };
		expect(planYields(plan, stepOfLevel(plan.level + 1, 1024), 1024)).toBe(false);
		expect(planYields(plan, stepOfLevel(plan.level + 2, 1024), 1024)).toBe(true);
	});
});
