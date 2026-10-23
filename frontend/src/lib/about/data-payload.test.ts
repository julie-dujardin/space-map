import { describe, it, expect } from 'vitest';

import {
	listedSources,
	mapFigures,
	modelFigures,
	totals,
	type AboutData,
	type MapPyramid,
	type MapSource,
	type Model,
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
		source: 'https://example.org/map',
		organisation: 'USGS',
		tiers: [
			{ name: 'low', width: 2048, height: 1024, size_bytes: 10, m_per_px: 400 },
			{ name: 'high', width: 4096, height: 2048, size_bytes: 30, m_per_px: 200 }
		],
		...overrides
	};
}

function model(overrides: Partial<Model> = {}): Model {
	return {
		slug: 'ace',
		tiers: [
			{ name: 'low', triangles: 300, size_bytes: 10 },
			{ name: 'high', triangles: 900, size_bytes: 30 }
		],
		sources: [{ organisation: 'NASA' }],
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

describe('modelFigures', () => {
	it('states the triangles of the high file and the size of each file', () => {
		expect(modelFigures(model())).toEqual({ triangles: 900, low_triangles: 300, size_bytes: 40 });
	});

	it('states one count where the two files have the same', () => {
		const tiers = [
			{ name: 'low', triangles: 900, size_bytes: 30 },
			{ name: 'high', triangles: 900, size_bytes: 30 }
		];
		expect(modelFigures(model({ tiers })).low_triangles).toBeUndefined();
	});

	it('states one count for a model of one file', () => {
		const tiers = [{ name: 'high', triangles: 1144, size_bytes: 9 }];
		expect(modelFigures(model({ tiers }))).toEqual({
			triangles: 1144,
			low_triangles: undefined,
			size_bytes: 9
		});
	});
});

describe('totals', () => {
	it('adds maps, patches, rings and models, and takes the worlds as stated', () => {
		const patched = pyramid({
			patches: [
				{
					id: 'site',
					name: 'Site',
					source: 'https://example.org/site',
					organisation: 'NASA',
					max_level: 5,
					lat: 0,
					lon: 0,
					tiles: 20,
					size_bytes: 500
				}
			]
		});
		const data: AboutData = {
			generated_at: '2026-10-13T18:00:00+00:00',
			worlds: 12,
			objects: [
				{ id: 'asteroid', count: 4, size_bytes: 300, localized: {}, sources: [] },
				{ id: 'probe', count: 2, size_bytes: 100, localized: {}, sources: [] }
			],
			rings: [
				{
					id: 'naif-699',
					name: 'Saturn',
					rings: [
						{
							id: 'primary',
							inner_radius_km: 74510,
							outer_radius_km: 140390,
							samples: 13177,
							km_per_sample: 5,
							size_bytes: 7,
							sources: []
						}
					]
				}
			],
			models: {
				worlds: [
					{ id: 'naif-401', name: 'Phobos', models: [{ ...model(), provenance: 'missions' }] }
				],
				craft: [{ kind: 'probe', models: [{ ...model(), objects: 0 }] }],
				lightcurve: { models: 9, worlds: 8, triangles: 9000, size_bytes: 90, sources: [] }
			},
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
			objects: 6,
			worlds: 12,
			maps: 3,
			patches: 1,
			tiles: 72,
			rings: 1,
			models: 11,
			size_bytes: 300 + 100 + 5040 + 500 + 40 + 40 + 7 + 40 + 40 + 90
		});
	});
});
