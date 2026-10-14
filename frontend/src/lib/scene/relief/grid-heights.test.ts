import { describe, expect, it } from 'vitest';
import { nestedStepLevel, planNestedGrid } from '$lib/scene/lod/terrain-grid';
import { MAP, NORTH } from '$lib/scene/lod/tile-window';
import { gridHeights, gridTiles, tileKey, tileOfKey } from './grid-heights';

const MAX_LEVEL = 6;
const TILE = 1024;

function grid(latDeg: number) {
	const theta = ((90 - latDeg) * Math.PI) / 180;
	const stepLevel = nestedStepLevel(1e-6, MAX_LEVEL, 24);
	return planNestedGrid(theta, 2, 1e-6, 0.004, MAX_LEVEL, 24, stepLevel);
}

/** A pyramid whose every pixel holds its level, times 1000. */
function flat(missing: (level: number) => boolean = () => false) {
	const tiles = new Map<number, Uint16Array>();
	return (key: number) => {
		const { level } = tileOfKey(key);
		if (missing(level)) return undefined;
		if (!tiles.has(level)) tiles.set(level, new Uint16Array(TILE * TILE).fill(level * 1000));
		return tiles.get(level);
	};
}

describe('tileKey', () => {
	it('gives back the tile it was made from', () => {
		expect(tileOfKey(tileKey(NORTH, 6, 31, 17))).toEqual({ chart: NORTH, level: 6, x: 31, y: 17 });
	});

	it('holds a tile of the deepest level of a patch', () => {
		const tile = { chart: MAP, level: 16, x: 131071, y: 65535 };
		expect(tileOfKey(tileKey(MAP, tile.level, tile.x, tile.y))).toEqual(tile);
	});
});

describe('gridTiles', () => {
	it('is a few tiles for each level, and the two coarsest of all', () => {
		const { rows, columns } = grid(-4.6);
		const keys = gridTiles(rows, columns, TILE);
		expect(keys.has(tileKey(MAP, 0, 0, 0)) && keys.has(tileKey(MAP, 0, 1, 0))).toBe(true);
		expect(keys.size).toBeLessThan(16);
		const levels = new Set([...keys].map((key) => tileOfKey(key).level));
		expect(levels.size).toBe(MAX_LEVEL + 1);
	});

	it('reads the cap near a pole, where the map would take a ring of tiles', () => {
		const { rows, columns } = grid(85);
		const fine = [...gridTiles(rows, columns, TILE)]
			.map(tileOfKey)
			.filter((tile) => tile.level === MAX_LEVEL);
		expect(fine.length).toBeGreaterThan(0);
		expect(fine.every((tile) => tile.chart === NORTH)).toBe(true);
	});
});

describe('gridTiles near a patch', () => {
	const DEEP = 9;
	// Around 4.6°S 137.4°E, the point of `grid` below, three levels down.
	const centre = { theta: ((90 + 4.6) * Math.PI) / 180, phi: ((137.4 + 180) * Math.PI) / 180 };
	const tileAt = (level: number) => ({
		x: Math.floor((centre.phi / (2 * Math.PI)) * (2 << level)),
		y: Math.floor((centre.theta / Math.PI) * (1 << level))
	});
	const deepGrid = () => {
		const stepLevel = nestedStepLevel(1e-6, DEEP, 16);
		return planNestedGrid(centre.theta, centre.phi, 1e-6, 0.004, DEEP, 16, stepLevel);
	};
	const fineTiles = (keys: Set<number>) =>
		[...keys].map(tileOfKey).filter((tile) => tile.level > MAX_LEVEL);

	it('asks for the tiles of the patch that its fine bands are on', () => {
		const { rows, columns } = deepGrid();
		const keys = gridTiles(rows, columns, TILE, MAX_LEVEL, () => true);
		const levels = new Set(fineTiles(keys).map((tile) => tile.level));
		expect([...levels].sort()).toEqual([7, 8, 9]);
		const { x, y } = tileAt(DEEP);
		expect(keys.has(tileKey(MAP, DEEP, x, y))).toBe(true);
	});

	it('asks for no tile that the patch does not have', () => {
		const { rows, columns } = deepGrid();
		// The patch is the one tile under the centre at each of its levels.
		const exists = (_chart: number, level: number, x: number, y: number) =>
			x === tileAt(level).x && y === tileAt(level).y;
		const keys = gridTiles(rows, columns, TILE, MAX_LEVEL, exists);
		const fine = fineTiles(keys);
		expect(fine.length).toBeGreaterThan(0);
		expect(fine.every((tile) => exists(MAP, tile.level, tile.x, tile.y))).toBe(true);
		// The ground beside it comes from the pyramid's own finest level.
		const own = [...keys].map(tileOfKey).filter((tile) => tile.level === MAX_LEVEL);
		expect(own.length).toBeGreaterThan(0);
	});

	it('gives a vertex beside the patch the height of the pyramid', () => {
		const { rows, columns } = deepGrid();
		const lookup = flat((level) => level > MAX_LEVEL);
		const heights = gridHeights(rows, columns, lookup, TILE, 65.535, -8);
		const cols = columns.at.length;
		const row = rows.level.indexOf(DEEP);
		const column = columns.level.indexOf(DEEP);
		expect(heights![row * cols + column]).toBeCloseTo(-2, 5);
	});
});

describe('gridHeights', () => {
	it('gives each vertex the level of its cell, as km above the sphere', () => {
		const { rows, columns } = grid(-4.6);
		const heights = gridHeights(rows, columns, flat(), TILE, 65.535, -8);
		const cols = columns.at.length;
		const row = rows.level.indexOf(MAX_LEVEL);
		const column = columns.level.indexOf(MAX_LEVEL);
		// 6000 of 65535 over a range of 65.535 km is 6 km.
		expect(heights![row * cols + column]).toBeCloseTo(-2, 5);
		expect(heights![0]).toBeCloseTo(-8, 5);
	});

	it('takes the level below where a tile did not come', () => {
		const { rows, columns } = grid(-4.6);
		const lookup = flat((level) => level === MAX_LEVEL);
		const heights = gridHeights(rows, columns, lookup, TILE, 65.535, -8);
		const cols = columns.at.length;
		const row = rows.level.indexOf(MAX_LEVEL);
		const column = columns.level.indexOf(MAX_LEVEL);
		expect(heights![row * cols + column]).toBeCloseTo(-3, 5);
	});

	it('gives nothing when the coarsest level is missing too', () => {
		const { rows, columns } = grid(-4.6);
		expect(gridHeights(rows, columns, () => undefined, TILE, 65.535, -8)).toBeNull();
	});
});
