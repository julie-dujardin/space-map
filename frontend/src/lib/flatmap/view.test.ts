import { describe, expect, it } from 'vitest';
import { createProjection } from './projection';
import { clampToBand, clampView, DEFAULT_MAX_ZOOM, Viewport, type ViewState } from './view';

const WIDTH = 800;
const HEIGHT = 400;

/** Where the middle of the frame lands, as a place. */
function centre(view: ViewState, id: Parameters<typeof createProjection>[0] = 'equirectangular') {
	const projection = createProjection(id);
	const viewport = new Viewport(projection, WIDTH, HEIGHT, view);
	return viewport.unproject(WIDTH / 2, HEIGHT / 2);
}

function clamp(
	view: ViewState,
	limits: Parameters<typeof clampView>[4],
	id: Parameters<typeof createProjection>[0] = 'equirectangular'
) {
	return clampView(view, createProjection(id), WIDTH, HEIGHT, limits);
}

/** The view held inside what there is to look at, and inside what the host
 *  allows the reader on top of that. */
describe('clampView', () => {
	it('never zooms out past the whole world, limits or none', () => {
		expect(clamp({ zoom: 0.2, centerX: 0, centerY: 0 }, {}).zoom).toBe(1);
		expect(clamp({ zoom: 0.2, centerX: 0, centerY: 0 }, { minZoom: 0.1 }).zoom).toBe(1);
	});

	it('leaves the zoom alone where no maximum is named', () => {
		expect(clamp({ zoom: 400, centerX: 0, centerY: 0 }, {}).zoom).toBe(400);
	});

	it('holds the zoom between the two the host named', () => {
		expect(clamp({ zoom: 40, centerX: 0, centerY: 0 }, { maxZoom: 8 }).zoom).toBe(8);
		expect(clamp({ zoom: 2, centerX: 0, centerY: 0 }, { minZoom: 4, maxZoom: 8 }).zoom).toBe(4);
	});

	it('holds the middle of the frame inside a latitude band', () => {
		const view = clamp({ zoom: 8, centerX: 0, centerY: 1.2 }, { maxZoom: 16, maxLat: 20 });
		expect(centre(view)![1]).toBeCloseTo(20, 6);
	});

	it('holds the middle of the frame inside a longitude band', () => {
		const view = clamp(
			{ zoom: 8, centerX: 2, centerY: 0 },
			{ maxZoom: 16, minLon: -30, maxLon: 30 }
		);
		expect(centre(view)![0]).toBeCloseTo(30, 6);
	});

	it('leaves a middle already inside the band where it is', () => {
		const asked: ViewState = { zoom: 8, centerX: 0.2, centerY: 0.1 };
		const view = clamp(asked, { minLon: -60, maxLon: 60, minLat: -40, maxLat: 40 });
		expect(view.centerX).toBeCloseTo(asked.centerX, 12);
		expect(view.centerY).toBeCloseTo(asked.centerY, 12);
	});

	it('wraps a world that tiles and stops a pointed one at its edge', () => {
		const extent = createProjection('equirectangular').extent;
		const wrapped = clamp({ zoom: 4, centerX: extent.maxX + 1, centerY: 0 }, {});
		expect(wrapped.centerX).toBeCloseTo(extent.minX + 1, 12);

		// Mollweide's seam is the point of its lens, not a straight edge, so the
		// frame stops there rather than coming round onto a second copy.
		const pointed = createProjection('mollweide').extent;
		const stopped = clamp({ zoom: 4, centerX: pointed.maxX + 1, centerY: 0 }, {}, 'mollweide');
		expect(stopped.centerX).toBeGreaterThan(0);
		expect(stopped.centerX).toBeLessThan(pointed.maxX);
	});

	it('still keeps the frame on the map when a band would take it off', () => {
		// The band asks for the pole; the frame may not run off the top of the map.
		const view = clamp({ zoom: 2, centerX: 0, centerY: 3 }, { minLat: 89, maxLat: 90 });
		const extent = createProjection('equirectangular').extent;
		expect(view.centerY).toBeLessThanOrEqual(extent.maxY);
	});
});

/** Where the projected world sits in a box of pixels. */
describe('Viewport', () => {
	const whole: ViewState = { zoom: 1, centerX: 0, centerY: 0 };

	it('draws a world that tiles again beside itself, and a pointed one once', () => {
		const repeat = (id: Parameters<typeof createProjection>[0]) =>
			new Viewport(createProjection(id), WIDTH, HEIGHT, whole).repeatsHorizontally;
		expect(repeat('equirectangular')).toBe(true);
		expect(repeat('mollweide')).toBe(false);
		expect(repeat('orthographic')).toBe(false);
	});

	it('stops repeating once the frame is wider than the world', () => {
		// A frame wider than 2:1 leaves the world short of its sides; a copy set
		// beside it would stand apart rather than fill a gap.
		const wide = new Viewport(createProjection('equirectangular'), WIDTH * 2, HEIGHT, whole);
		expect(wide.repeatsHorizontally).toBe(false);
	});

	it('offers the copies of the world that reach into the frame, its own first', () => {
		const projection = createProjection('equirectangular');
		// The whole world fills the frame exactly: neither neighbour shows.
		expect(new Viewport(projection, WIDTH, HEIGHT, whole).repeatShifts).toEqual([0]);
		// Panned east to the seam, the copy to the east fills the right half.
		const seam = new Viewport(projection, WIDTH, HEIGHT, { ...whole, centerX: Math.PI });
		expect(seam.repeatShifts).toEqual([0, WIDTH]);
		// Panned west, the other one.
		const west = new Viewport(projection, WIDTH, HEIGHT, { ...whole, centerX: -Math.PI });
		expect(west.repeatShifts).toEqual([0, -WIDTH]);
		expect(new Viewport(createProjection('mollweide'), WIDTH, HEIGHT, whole).repeatShifts).toEqual([
			0
		]);
	});
});

/** The rule a globe's centre is held to, which cannot go through the plane. */
describe('clampToBand', () => {
	it('leaves a place inside the band alone', () => {
		expect(clampToBand(12, 48, { minLon: 0, maxLon: 30, minLat: 40, maxLat: 60 })).toEqual([
			12, 48
		]);
	});

	it('brings latitude to the nearer edge', () => {
		expect(clampToBand(0, 80, { maxLat: 60 })[1]).toBe(60);
		expect(clampToBand(0, -80, { minLat: -60 })[1]).toBe(-60);
	});

	it('reads a longitude band that runs through the antimeridian', () => {
		expect(clampToBand(178, 0, { minLon: 170, maxLon: -170 })[0]).toBe(178);
		expect(clampToBand(-178, 0, { minLon: 170, maxLon: -170 })[0]).toBe(-178);
		expect(clampToBand(0, 0, { minLon: 170, maxLon: -170 })[0]).toBe(170);
	});

	it('reads one edge alone as the band that reaches the antimeridian', () => {
		// `maxLon: 30` is the band −180 to 30, so what falls outside it is the
		// arc past 30, and 114 sits nearer that arc's other end.
		expect(clampToBand(20, 0, { maxLon: 30 })[0]).toBe(20);
		expect(clampToBand(114, 0, { maxLon: 30 })[0]).toBe(-180);
	});

	it('reads −180 to 180 as the whole way round', () => {
		expect(clampToBand(-74, 0, { minLon: -180, maxLon: 180 })[0]).toBe(-74);
		expect(clampToBand(-74, 0, { minLon: -180 })[0]).toBe(-74);
	});

	it('lets a place through where the band names nothing', () => {
		expect(clampToBand(-74, 41, {})).toEqual([-74, 41]);
	});
});

describe('DEFAULT_MAX_ZOOM', () => {
	it('is what a map with no limits of its own holds the reader to', () => {
		expect(clamp({ zoom: 100, centerX: 0, centerY: 0 }, { maxZoom: DEFAULT_MAX_ZOOM }).zoom).toBe(
			16
		);
	});
});
