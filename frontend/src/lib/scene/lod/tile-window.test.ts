import { describe, expect, it } from 'vitest';
import {
	type Chart,
	FIRST_TILE_LEVEL,
	MAP,
	NORTH,
	SOUTH,
	WINDOW_TILES,
	cameraChart,
	chartColumns,
	chartPoint,
	chartRows,
	neededLevel,
	placeWindow,
	slotTile,
	windowChain
} from './tile-window';

/** Unit direction of a latitude and an east longitude, as the sphere mesh has it. */
function direction(latDeg: number, lonDeg: number): [number, number, number] {
	const lat = (latDeg * Math.PI) / 180;
	const lon = (lonDeg * Math.PI) / 180;
	return [Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon)];
}

function sinDeg(latDeg: number): number {
	return Math.sin((latDeg * Math.PI) / 180);
}

describe('neededLevel', () => {
	const projScale = 935; // 1080 px tall at a 60° field of view

	it('is negative far away, where two tiles already outdo the screen', () => {
		expect(neededLevel(1, 100, projScale, 6)).toBeLessThan(1);
	});

	it('rises by one each time the height above the ground halves', () => {
		const at = (height: number) => neededLevel(1, 1 + height, projScale, 20);
		expect(at(0.01) - at(0.02)).toBe(1);
		expect(at(0.005) - at(0.01)).toBe(1);
	});

	it('stops at the finest level the pyramid has', () => {
		expect(neededLevel(1, 1.000001, projScale, 6)).toBe(6);
	});
});

describe('chart grids', () => {
	it('gives the map two columns for each row', () => {
		expect([chartColumns(MAP, 4), chartRows(MAP, 4)]).toEqual([32, 16]);
	});

	it('gives a cap a square that is one window at the first tile level', () => {
		expect(chartColumns(NORTH, FIRST_TILE_LEVEL)).toBe(WINDOW_TILES);
		expect(chartRows(SOUTH, FIRST_TILE_LEVEL)).toBe(WINDOW_TILES);
		expect(chartColumns(NORTH, 6)).toBe(32);
	});
});

describe('chartPoint', () => {
	it('counts the map east from 180°W and south from the north pole', () => {
		const origin = chartPoint(MAP, ...direction(0, 0));
		expect(origin.x).toBeCloseTo(0.5);
		expect(origin.y).toBeCloseTo(0.5);
		expect(chartPoint(MAP, ...direction(45, 90)).x).toBeCloseTo(0.75);
		expect(chartPoint(MAP, ...direction(45, 90)).y).toBeCloseTo(0.25);
		expect(chartPoint(MAP, ...direction(0, -179)).x).toBeCloseTo(1 / 360);
	});

	it('puts a pole at the middle of its cap', () => {
		for (const [chart, lat] of [
			[NORTH, 90],
			[SOUTH, -90]
		] as [Chart, number][]) {
			const pole = chartPoint(chart, ...direction(lat, 0));
			expect(pole.x).toBeCloseTo(0.5);
			expect(pole.y).toBeCloseTo(0.5);
		}
	});

	it('touches latitude 45° at the middle of a cap side, the prime meridian to the right', () => {
		const right = chartPoint(NORTH, ...direction(45, 0));
		expect(right.x).toBeCloseTo(1);
		expect(right.y).toBeCloseTo(0.5);
		expect(chartPoint(SOUTH, ...direction(-45, 0)).x).toBeCloseTo(1);
	});

	it('turns east counter-clockwise in the north and clockwise in the south', () => {
		// 90°E is up the north cap and down the south one.
		expect(chartPoint(NORTH, ...direction(45, 90)).y).toBeCloseTo(0);
		expect(chartPoint(SOUTH, ...direction(-45, 90)).y).toBeCloseTo(1);
	});

	it('places latitude 60° at the stereographic distance from the pole', () => {
		const at = chartPoint(NORTH, ...direction(60, 0));
		const reach = Math.tan((15 * Math.PI) / 180) / Math.tan(Math.PI / 8);
		expect(at.x).toBeCloseTo(0.5 + reach / 2);
	});
});

describe('cameraChart', () => {
	it('is the map at low latitudes and the cap of the hemisphere near a pole', () => {
		expect(cameraChart(sinDeg(30))).toBe(MAP);
		expect(cameraChart(sinDeg(80))).toBe(NORTH);
		expect(cameraChart(sinDeg(-80))).toBe(SOUTH);
	});

	it('keeps the chart it had near the line between two', () => {
		expect(cameraChart(sinDeg(60), MAP)).toBe(MAP);
		expect(cameraChart(sinDeg(60), NORTH)).toBe(NORTH);
		expect(cameraChart(sinDeg(-60), SOUTH)).toBe(SOUTH);
	});

	it('does not keep the cap of the other pole', () => {
		expect(cameraChart(sinDeg(60), SOUTH)).toBe(MAP);
	});
});

describe('windowChain', () => {
	it('lists a window per level, finest first, on the camera chart', () => {
		expect(windowChain(6, 3, MAP, 0)).toEqual([
			{ chart: MAP, level: 6 },
			{ chart: MAP, level: 5 },
			{ chart: MAP, level: 4 }
		]);
	});

	it('stops at the first tile level', () => {
		expect(windowChain(4, 6, MAP, 0).map((link) => link.level)).toEqual([4, 3]);
	});

	it('is empty below the first tile level', () => {
		expect(windowChain(FIRST_TILE_LEVEL - 1, 6, MAP, 0)).toEqual([]);
	});

	it('adds the coarsest level on the other chart where both reach the camera', () => {
		expect(windowChain(4, 6, MAP, sinDeg(50))).toEqual([
			{ chart: MAP, level: 4 },
			{ chart: MAP, level: 3 },
			{ chart: NORTH, level: 3 }
		]);
		expect(windowChain(4, 6, SOUTH, sinDeg(-70)).at(-1)).toEqual({ chart: MAP, level: 3 });
	});

	it('does not add it far from the caps, or with no place left', () => {
		expect(windowChain(4, 6, MAP, sinDeg(30))).toHaveLength(2);
		expect(windowChain(4, 2, MAP, sinDeg(50))).toHaveLength(2);
		// The chain did not reach the coarsest level.
		expect(windowChain(6, 3, NORTH, sinDeg(80))).toHaveLength(3);
	});
});

describe('placeWindow', () => {
	it('centres on the point under the camera', () => {
		// Level 4: 32 columns, 16 rows. The map centre is tile (16, 8).
		expect(placeWindow(MAP, 4, 0.5, 0.5)).toEqual({ chart: MAP, level: 4, tx0: 14, ty0: 6 });
	});

	it('wraps the map across the 180° meridian', () => {
		expect(placeWindow(MAP, 4, 0.01, 0.5).tx0).toBe(chartColumns(MAP, 4) - 2);
	});

	it('stops at the poles instead of leaving the map', () => {
		expect(placeWindow(MAP, 4, 0.5, 0.001).ty0).toBe(0);
		expect(placeWindow(MAP, 4, 0.5, 0.999).ty0).toBe(chartRows(MAP, 4) - WINDOW_TILES);
	});

	it('stops at the sides of a cap, also for a camera past them', () => {
		const last = chartColumns(NORTH, 5) - WINDOW_TILES;
		expect(placeWindow(NORTH, 5, 0.99, 0.5).tx0).toBe(last);
		expect(placeWindow(NORTH, 5, 1.4, -0.3)).toEqual({ chart: NORTH, level: 5, tx0: last, ty0: 0 });
	});

	it('covers the whole cap at the first tile level', () => {
		expect(placeWindow(SOUTH, FIRST_TILE_LEVEL, 0.9, 0.1)).toMatchObject({ tx0: 0, ty0: 0 });
	});

	it('holds still while the camera stays near its middle', () => {
		const first = placeWindow(MAP, 4, 0.5, 0.5);
		const nudged = placeWindow(MAP, 4, 0.5 + 0.5 / chartColumns(MAP, 4), 0.5, first);
		expect(nudged).toBe(first);
	});

	it('follows once the camera is most of a tile off centre', () => {
		const first = placeWindow(MAP, 4, 0.5, 0.5);
		const moved = placeWindow(MAP, 4, 0.5 + 1 / chartColumns(MAP, 4), 0.5, first);
		expect(moved.tx0).toBe(first.tx0 + 1);
	});

	it('does not chase a camera that sits past the last row at a pole', () => {
		const first = placeWindow(MAP, 4, 0.5, 0.001);
		expect(placeWindow(MAP, 4, 0.5, 0.0001, first)).toBe(first);
	});

	it('holds across the 180° meridian', () => {
		const first = placeWindow(MAP, 4, 0.999, 0.5);
		expect(placeWindow(MAP, 4, 0.001, 0.5, first)).toBe(first);
	});

	it('starts afresh on another chart or level', () => {
		const first = placeWindow(MAP, 5, 0.5, 0.5);
		expect(placeWindow(NORTH, 5, 0.5, 0.5, first).chart).toBe(NORTH);
		expect(placeWindow(MAP, 4, 0.5, 0.5, first).level).toBe(4);
	});
});

describe('slotTile', () => {
	it('gives every slot a different tile of the window', () => {
		for (const placement of [
			placeWindow(MAP, 5, 0.37, 0.61),
			placeWindow(MAP, 4, 0.999, 0.5),
			placeWindow(NORTH, 6, 0.8, 0.3)
		]) {
			const seen = new Set<string>();
			for (let sy = 0; sy < WINDOW_TILES; sy++) {
				for (let sx = 0; sx < WINDOW_TILES; sx++) {
					const { x, y } = slotTile(placement, sx, sy);
					expect(x % WINDOW_TILES).toBe(sx);
					expect(y % WINDOW_TILES).toBe(sy);
					expect(x).toBeLessThan(chartColumns(placement.chart, placement.level));
					expect(y - placement.ty0).toBeGreaterThanOrEqual(0);
					expect(y - placement.ty0).toBeLessThan(WINDOW_TILES);
					seen.add(`${x}/${y}`);
				}
			}
			expect(seen.size).toBe(WINDOW_TILES * WINDOW_TILES);
		}
	});

	it('keeps a tile in its slot when the window moves', () => {
		const first = placeWindow(MAP, 5, 0.5, 0.5);
		const moved = placeWindow(MAP, 5, 0.5 + 1 / chartColumns(MAP, 5), 0.5);
		let kept = 0;
		for (let sy = 0; sy < WINDOW_TILES; sy++) {
			for (let sx = 0; sx < WINDOW_TILES; sx++) {
				const a = slotTile(first, sx, sy);
				const b = slotTile(moved, sx, sy);
				if (a.x === b.x && a.y === b.y) kept++;
			}
		}
		expect(kept).toBe(WINDOW_TILES * (WINDOW_TILES - 1));
	});
});
