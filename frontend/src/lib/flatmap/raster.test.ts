import { describe, expect, it } from 'vitest';
import { MAP, NORTH, SOUTH } from '$lib/scene/lod/tile-window';
import { createProjection, type ProjectionId, type ProjectionOptions } from './projection';
import { InverseLookup, compositeLayers, type DetailRaster, type RasterImage } from './raster';
import { chartFraction } from './tile-plan';
import { Viewport } from './view';

const WIDTH = 96;
const HEIGHT = 64;

function viewportOf(
	id: ProjectionId,
	options: ProjectionOptions,
	zoom: number,
	at?: [lon: number, lat: number]
): Viewport {
	const projection = createProjection(id, options);
	const plane = at ? projection.forward(at[0], at[1])! : [0, 0];
	return new Viewport(projection, WIDTH, HEIGHT, { zoom, centerX: plane[0], centerY: plane[1] });
}

/** A picture of one colour. */
function plain(width: number, height: number, rgb: [number, number, number]): RasterImage {
	const data = new Uint8ClampedArray(width * height * 4);
	for (let i = 0; i < width * height; i++) data.set([...rgb, 255], i * 4);
	return { width, height, data };
}

function composite(lookup: InverseLookup, base: RasterImage, detail: DetailRaster[]) {
	const target = { width: WIDTH, height: HEIGHT, data: new Uint8ClampedArray(WIDTH * HEIGHT * 4) };
	compositeLayers(
		lookup,
		[{ image: base, opacity: 1, blend: 'normal', detail }],
		target as ImageData
	);
	return (px: number, py: number) => [
		...target.data.slice((py * WIDTH + px) * 4, (py * WIDTH + px) * 4 + 3)
	];
}

/** Where each pixel of a frame reads from. */
describe('InverseLookup', () => {
	it('gives the place of each pixel, as an offset from the middle of the frame', () => {
		const viewport = viewportOf('equalEarth', { centerLon: 180 }, 40, [179.9, 30]);
		const lookup = new InverseLookup(viewport, WIDTH, HEIGHT);
		for (const [px, py] of [
			[0, 0],
			[95, 63],
			[48, 32],
			[10, 50]
		]) {
			const place = viewport.unproject(px + 0.5, py + 0.5)!;
			const [u, v] = chartFraction(MAP, place[0], place[1]);
			const i = py * WIDTH + px;
			const across = lookup.refU + lookup.u[i];
			expect(across - Math.floor(across)).toBeCloseTo(u, 6);
			expect(lookup.refV + lookup.v[i]).toBeCloseTo(v, 6);
			// The short way around, across the ±180° meridian.
			expect(Math.abs(lookup.u[i])).toBeLessThan(0.05);
		}
	});

	it('keeps the precision of the deepest tile level', () => {
		// Each pixel of the frame is one pixel of level 16.
		const zoom = (2048 * 2 ** 16) / WIDTH;
		const viewport = viewportOf('equirectangular', {}, zoom, [77.45, 18.44]);
		const lookup = new InverseLookup(viewport, WIDTH, HEIGHT);
		const across = 2048 * 2 ** 16;
		const column = (i: number) => (lookup.refU * across + lookup.u[i] * across) % 1024;
		for (let px = 1; px < WIDTH; px++) {
			const step = column(32 * WIDTH + px) - column(32 * WIDTH + px - 1);
			expect((step + 1024) % 1024).toBeCloseTo(1, 3);
		}
	});

	it.each([
		['orthographic', NORTH, { centerLon: 20, centerLat: 72 }, 6],
		['orthographic', NORTH, { centerLon: -140, centerLat: 89.5 }, 3000],
		['stereographic', SOUTH, { centerLon: 70, centerLat: -80 }, 40]
	] as const)('gives the cap coordinates of a %s frame', (id, chart, options, zoom) => {
		const viewport = viewportOf(id, options, zoom);
		const lookup = new InverseLookup(viewport, WIDTH, HEIGHT);
		const cap = lookup.offsets(chart);
		// One pixel of the frame, in cap coordinates.
		const pixel = Math.hypot(cap.x[33] - cap.x[32], cap.y[33] - cap.y[32]);
		for (let py = 0; py < HEIGHT; py += 7) {
			for (let px = 0; px < WIDTH; px += 5) {
				const place = viewport.unproject(px + 0.5, py + 0.5);
				if (!place) continue;
				const [x, y] = chartFraction(chart, place[0], place[1]);
				const i = py * WIDTH + px;
				expect(Math.abs(cap.refX + cap.x[i] - x) / pixel).toBeLessThan(0.05);
				expect(Math.abs(cap.refY + cap.y[i] - y) / pixel).toBeLessThan(0.05);
			}
		}
	});
});

/** A picture with tile windows over it. */
describe('compositeLayers', () => {
	const red = plain(8, 4, [255, 0, 0]);

	/** A window of level 0 of the map, 8 × 4 pixels for the whole body. */
	function mapWindow(x0: number, width: number, fill = true): DetailRaster {
		const data = new Uint8ClampedArray(width * 4 * 4);
		if (fill) for (let i = 0; i < width * 4; i++) data.set([0, 255, 0, 255], i * 4);
		return { chart: MAP, level: 0, tileSize: 4, x0, y0: 0, width, height: 4, data };
	}

	it('draws a window over the picture, and the picture beside it', () => {
		const viewport = viewportOf('equalEarth', {}, 1);
		const at = composite(new InverseLookup(viewport, WIDTH, HEIGHT), red, [mapWindow(4, 2)]);
		// Columns 4 and 5 of 8 are longitudes 0° to 90°.
		const east = viewport.project(45, 0)!.map(Math.floor);
		const west = viewport.project(-45, 0)!.map(Math.floor);
		const far = viewport.project(135, 0)!.map(Math.floor);
		expect(at(east[0], east[1])).toEqual([0, 255, 0]);
		expect(at(west[0], west[1])).toEqual([255, 0, 0]);
		expect(at(far[0], far[1])).toEqual([255, 0, 0]);
	});

	it('draws the picture where a window has no tile', () => {
		const viewport = viewportOf('equalEarth', {}, 1);
		const at = composite(new InverseLookup(viewport, WIDTH, HEIGHT), red, [mapWindow(4, 2, false)]);
		const east = viewport.project(45, 0)!.map(Math.floor);
		expect(at(east[0], east[1])).toEqual([255, 0, 0]);
	});

	it('draws the next window where the first has no tile', () => {
		const viewport = viewportOf('equalEarth', {}, 1);
		const at = composite(new InverseLookup(viewport, WIDTH, HEIGHT), red, [
			mapWindow(4, 2, false),
			mapWindow(4, 2)
		]);
		const east = viewport.project(45, 0)!.map(Math.floor);
		expect(at(east[0], east[1])).toEqual([0, 255, 0]);
	});

	it('draws a window that counts its columns from another turn of the globe', () => {
		const viewport = viewportOf('orthographic', { centerLon: 180, centerLat: 0 }, 1);
		const lookup = new InverseLookup(viewport, WIDTH, HEIGHT);
		// Columns 7 and 8: longitudes 135° to 225°, across the ±180° meridian.
		for (const x0 of [7, -1, 15]) {
			const at = composite(lookup, red, [mapWindow(x0, 2)]);
			expect(at(WIDTH / 2 - 4, HEIGHT / 2)).toEqual([0, 255, 0]);
			expect(at(WIDTH / 2 + 4, HEIGHT / 2)).toEqual([0, 255, 0]);
		}
	});

	it('draws a cap window on the ground of its cap', () => {
		const viewport = viewportOf('orthographic', { centerLon: 0, centerLat: 90 }, 1);
		const lookup = new InverseLookup(viewport, WIDTH, HEIGHT);
		// Level 1 of a cap is one tile. The right half is the side of the prime meridian.
		const data = new Uint8ClampedArray(2 * 4 * 4);
		for (let i = 0; i < 8; i++) data.set([0, 0, 255, 255], i * 4);
		const cap: DetailRaster = {
			chart: NORTH,
			level: 1,
			tileSize: 4,
			x0: 2,
			y0: 0,
			width: 2,
			height: 4,
			data
		};
		const at = composite(lookup, red, [cap]);
		const prime = viewport.project(0, 70)!.map(Math.floor);
		const opposite = viewport.project(180, 70)!.map(Math.floor);
		expect(at(prime[0], prime[1])).toEqual([0, 0, 255]);
		expect(at(opposite[0], opposite[1])).toEqual([255, 0, 0]);
	});
});
