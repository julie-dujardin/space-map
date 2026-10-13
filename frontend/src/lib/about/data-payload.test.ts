import { describe, it, expect } from 'vitest';

import {
	listedSources,
	mapFigures,
	totals,
	type AboutData,
	type MapPyramid,
	type MapSource,
	type WorldMap
} from './data-payload';

function pyramid(overrides: Partial<MapPyramid> = {}): MapPyramid {
	return {
		max_level: 2,
		width: 8192,
		height: 4096,
		m_per_px: 100,
		tiles: 52,
		size_bytes: 5000,
		sources: [{ role: 'base', width: 8000, m_per_px: 100 }],
		...overrides
	};
}

function map(overrides: Partial<WorldMap> = {}): WorldMap {
	return {
		id: 'naif-499',
		layer: 'surface',
		tiers: [
			{ name: 'low', width: 2048, height: 1024, size_bytes: 10, m_per_px: 400 },
			{ name: 'high', width: 4096, height: 2048, size_bytes: 30, m_per_px: 200 }
		],
		...overrides
	};
}

describe('mapFigures', () => {
	it('states the pyramid where a map has one, and counts the images in its size', () => {
		expect(mapFigures(map({ tiles: pyramid() }))).toEqual({
			m_per_px: 100,
			width: 8192,
			height: 4096,
			tiles: 52,
			size_bytes: 5040,
			height_step_m: undefined
		});
	});

	it('states the finest image of a map with no pyramid', () => {
		const figures = mapFigures(map());
		expect(figures).toMatchObject({ m_per_px: 200, width: 4096, height: 2048, size_bytes: 40 });
		expect(figures.tiles).toBeUndefined();
	});

	it('takes the height step of the pyramid over that of the images', () => {
		const heights = map({ layer: 'topography', height_step_m: 116 });
		expect(mapFigures(heights).height_step_m).toBe(116);
		const tiled = { ...heights, tiles: pyramid({ height_step_m: 1 }) };
		expect(mapFigures(tiled).height_step_m).toBe(1);
	});

	it('has no size in pixels for a map with no image', () => {
		expect(mapFigures(map({ tiers: [] }))).toMatchObject({ width: undefined, size_bytes: 0 });
	});
});

describe('listedSources', () => {
	const colour: MapSource = { role: 'base', width: 23059, m_per_px: 925 };

	it('lists nothing for a pyramid of one source', () => {
		expect(listedSources(pyramid())).toEqual([]);
	});

	it('keeps the band of a source that covers part of the body', () => {
		const detail: MapSource = { role: 'detail', width: 4267800, m_per_px: 5, lat_range: [-88, 88] };
		expect(listedSources(pyramid({ sources: [colour, detail] }))).toEqual([colour, detail]);
	});

	it('joins bands of one pixel size that cover the body between them', () => {
		const bands: [number, number][] = [
			[-60, 60],
			[60, 90],
			[-90, -60]
		];
		const details = bands.map(
			(lat_range): MapSource => ({ role: 'detail', width: 109440, m_per_px: 100, lat_range })
		);
		expect(listedSources(pyramid({ sources: [colour, ...details] }))).toEqual([
			colour,
			{ role: 'detail', width: 109440, m_per_px: 100 }
		]);
	});

	it('lists an inset with its band beside the map it replaces', () => {
		const base: MapSource = { role: 'base', width: 92160, m_per_px: 118 };
		const inset: MapSource = { role: 'inset', width: 184320, m_per_px: 59, lat_range: [-60, 60] };
		expect(listedSources(pyramid({ sources: [base, inset] }))).toEqual([base, inset]);
	});
});

describe('totals', () => {
	it('adds maps, patches and their tiles over all worlds', () => {
		const patched = pyramid({
			patches: [
				{ id: 'site', name: 'Site', max_level: 5, lat: 0, lon: 0, tiles: 20, size_bytes: 500 }
			]
		});
		const data: AboutData = {
			generated_at: '2026-10-13T18:00:00+00:00',
			systems: [
				{
					id: 'naif-4',
					name: 'Mars',
					worlds: [
						{ id: 'naif-499', name: 'Mars', maps: [map({ tiles: patched }), map({ id: 'x' })] }
					]
				},
				{ id: null, name: null, worlds: [{ id: 'naif-2000001', name: 'Ceres', maps: [map()] }] }
			]
		};
		expect(totals(data)).toEqual({
			worlds: 2,
			maps: 3,
			patches: 1,
			tiles: 72,
			size_bytes: 5040 + 500 + 40 + 40
		});
	});
});
