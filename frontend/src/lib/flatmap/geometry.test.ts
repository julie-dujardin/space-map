import { describe, expect, it } from 'vitest';
import {
	angularDistance,
	boxRing,
	densify,
	graticule,
	pathFor,
	projectSegments,
	smallCircle
} from './geometry';
import { createProjection } from './projection';
import { Viewport } from './view';

/** A square frame showing the whole world, so screen pixels are easy to reason
 *  about: the equirectangular map then spans the full 800 across. */
function viewport(id: Parameters<typeof createProjection>[0] = 'equirectangular') {
	return new Viewport(createProjection(id), 800, 400, { zoom: 1, centerX: 0, centerY: 0 });
}

describe('angularDistance', () => {
	it('measures along the sphere, not along the coordinates', () => {
		expect(angularDistance({ lon: 0, lat: 0 }, { lon: 90, lat: 0 })).toBeCloseTo(90, 9);
		expect(angularDistance({ lon: 0, lat: -90 }, { lon: 0, lat: 90 })).toBeCloseTo(180, 9);
		// Two places a degree of longitude apart are closer together near the pole.
		expect(angularDistance({ lon: 0, lat: 60 }, { lon: 1, lat: 60 })).toBeCloseTo(0.5, 2);
	});

	it('takes the short way over the seam', () => {
		expect(angularDistance({ lon: 179, lat: 0 }, { lon: -179, lat: 0 })).toBeCloseTo(2, 9);
	});
});

describe('densify', () => {
	it('adds steps in proportion to how long the segment is', () => {
		const short = densify([
			{ lon: 0, lat: 0 },
			{ lon: 2, lat: 0 }
		]);
		const long = densify([
			{ lon: 0, lat: 0 },
			{ lon: 100, lat: 0 }
		]);
		expect(short).toHaveLength(2);
		expect(long.length).toBeGreaterThan(40);
	});

	it('keeps the points it was given, in order', () => {
		const given = [
			{ lon: 0, lat: 0 },
			{ lon: 40, lat: 10 },
			{ lon: 80, lat: -10 }
		];
		const out = densify(given);
		expect(out[0]).toEqual(given[0]);
		expect(out.at(-1)).toEqual(given[2]);
		expect(out).toContainEqual(given[1]);
	});

	it('walks a parallel when told to interpolate linearly', () => {
		const out = densify(
			[
				{ lon: -60, lat: 45 },
				{ lon: 60, lat: 45 }
			],
			{ interpolate: 'linear' }
		);
		for (const p of out) expect(p.lat).toBeCloseTo(45, 9);
	});

	it('bulges poleward on a geodesic between the same two places', () => {
		const out = densify(
			[
				{ lon: -60, lat: 45 },
				{ lon: 60, lat: 45 }
			],
			{ interpolate: 'geodesic' }
		);
		const middle = out[Math.floor(out.length / 2)];
		expect(middle.lon).toBeCloseTo(0, 6);
		// The great circle rides well north of the parallel joining the ends.
		expect(middle.lat).toBeGreaterThan(50);
	});

	it('crosses the seam rather than going the long way round', () => {
		const out = densify([
			{ lon: 170, lat: 0 },
			{ lon: -170, lat: 0 }
		]);
		// Every step stays out near the seam; none doubles back through zero.
		for (const p of out) expect(Math.abs(p.lon)).toBeGreaterThan(169);
	});

	it('returns to the first point when closed', () => {
		const out = densify(
			[
				{ lon: 0, lat: 0 },
				{ lon: 10, lat: 0 },
				{ lon: 10, lat: 10 }
			],
			{ closed: true }
		);
		expect(out.at(-1)).toEqual({ lon: 0, lat: 0 });
	});
});

describe('projectSegments', () => {
	it('is one run for a line that stays on the map', () => {
		const segments = projectSegments(
			densify([
				{ lon: -40, lat: 0 },
				{ lon: 40, lat: 0 }
			]),
			viewport()
		);
		expect(segments).toHaveLength(1);
	});

	it('breaks in two where a line wraps over the seam', () => {
		const segments = projectSegments(
			densify([
				{ lon: 160, lat: 0 },
				{ lon: -160, lat: 0 }
			]),
			viewport()
		);
		expect(segments).toHaveLength(2);
		// And neither piece strides across the frame.
		for (const s of segments) {
			const xs = s.map(([x]) => x);
			expect(Math.max(...xs) - Math.min(...xs)).toBeLessThan(400);
		}
	});

	it('drops the part hidden behind a globe', () => {
		const segments = projectSegments(
			densify([
				{ lon: -60, lat: 0 },
				{ lon: 60, lat: 0 }
			]),
			new Viewport(createProjection('orthographic', { centerLon: 180 }), 400, 400, {
				zoom: 1,
				centerX: 0,
				centerY: 0
			})
		);
		// The whole run faces away from a globe centred on the far side.
		expect(segments).toHaveLength(0);
	});

	it('keeps the visible half of a line that goes round the limb', () => {
		const segments = projectSegments(
			densify([
				{ lon: 0, lat: 0 },
				{ lon: 170, lat: 0 }
			]),
			new Viewport(createProjection('orthographic', { centerLon: 0 }), 400, 400, {
				zoom: 1,
				centerX: 0,
				centerY: 0
			})
		);
		expect(segments).toHaveLength(1);
		expect(segments[0].length).toBeGreaterThan(10);
	});
});

describe('pathFor', () => {
	it('is empty for nothing to draw', () => {
		expect(pathFor([], viewport())).toBe('');
		expect(pathFor([{ lon: 0, lat: 0 }], viewport())).toBe('');
	});

	it('closes a ring that survived in one piece', () => {
		const d = pathFor(boxRing(-10, 10, -10, 20), viewport(), { closed: true });
		expect(d.endsWith('Z')).toBe(true);
		expect(d.match(/M/g)).toHaveLength(1);
	});

	it('cuts a ring that reaches over the seam into two closed pieces', () => {
		// A chart cell straddling the antimeridian exists on the Moon and on
		// Mercury. Drawn as one path it would jump the width of the world; left
		// open it could not be filled.
		const view = viewport();
		const d = pathFor(boxRing(-10, 10, 170, 20), view, { closed: true });
		expect(d.match(/M/g)).toHaveLength(2);
		expect(d.match(/Z/g)).toHaveLength(2);
		// One piece finishes against each edge of the map.
		expect(d).toContain(`L${view.width.toFixed(2)}`);
		expect(d).toContain('M0.00 ');
	});

	it('cuts a cap covering every longitude into the two halves it has to be', () => {
		// Every gridded body has one of these at each pole — a row of a single
		// full-longitude cell.
		const view = viewport();
		const d = pathFor(boxRing(80, 90, 0, 360), view, { closed: true });
		expect(d.match(/M/g)).toHaveLength(2);
		expect(d.match(/Z/g)).toHaveLength(2);
		// Between them the two halves span the whole map, and neither reaches
		// back across it.
		const xs = [...d.matchAll(/[ML](-?[\d.]+)/g)].map((m) => Number(m[1]));
		expect(Math.min(...xs)).toBeCloseTo(0, 1);
		expect(Math.max(...xs)).toBeCloseTo(view.width, 1);
	});

	it('cuts at the seam the projection actually has, not at 180°', () => {
		// Turning the central meridian moves the seam with it, so a cell that was
		// whole is cut and one that was cut comes back whole.
		const turned = new Viewport(createProjection('equirectangular', { centerLon: 90 }), 800, 400, {
			zoom: 1,
			centerX: 0,
			centerY: 0
		});
		expect(pathFor(boxRing(-10, 10, 170, 20), turned, { closed: true }).match(/M/g)).toHaveLength(
			1
		);
		expect(pathFor(boxRing(-10, 10, -100, 20), turned, { closed: true }).match(/M/g)).toHaveLength(
			2
		);
	});

	it('leaves what the limb of a globe cuts open', () => {
		// There the shape really does carry on out of sight, so joining the loose
		// ends would draw an edge it does not have.
		const globe = new Viewport(createProjection('orthographic'), 800, 800, {
			zoom: 1,
			centerX: 0,
			centerY: 0
		});
		const d = pathFor(boxRing(-10, 10, 60, 60), globe, { closed: true });
		expect(d).not.toContain('Z');
	});
});

describe('boxRing', () => {
	it('walks the two parallels of a chart box', () => {
		const ring = boxRing(0, 30, 10, 40);
		expect(ring.every((p) => p.lat === 0 || p.lat === 30)).toBe(true);
		expect(Math.min(...ring.map((p) => p.lon))).toBe(10);
		expect(Math.max(...ring.map((p) => p.lon))).toBe(50);
	});
});

describe('smallCircle', () => {
	it('is every place the same distance from its centre', () => {
		const centre = { lon: 20, lat: 35 };
		for (const p of smallCircle(centre, 12, 36)) {
			expect(angularDistance(centre, p)).toBeCloseTo(12, 6);
		}
	});

	it('closes round a pole instead of stopping at it', () => {
		const ring = smallCircle({ lon: 0, lat: 90 }, 20, 36);
		for (const p of ring) expect(p.lat).toBeCloseTo(70, 6);
		// A cap round the pole reaches every longitude, rather than collapsing
		// onto the centre's own meridian.
		const lons = ring.map((p) => p.lon);
		expect(Math.max(...lons) - Math.min(...lons)).toBeGreaterThanOrEqual(350);
	});
});

describe('graticule', () => {
	it('draws a grid at the step it is asked for', () => {
		const lines = graticule(30);
		// 12 meridians round, and 5 parallels between the poles.
		expect(lines).toHaveLength(17);
	});

	it('runs its parallels the whole way round', () => {
		// A parallel given only as its two ends is half the world long, and that
		// is exactly the segment whose direction is ambiguous — it used to be
		// filled in the wrong way round, leaving half the map without any.
		const vp = viewport();
		for (const line of graticule(30)) {
			const lats = new Set(line.map((p) => p.lat));
			if (lats.size !== 1) continue; // a meridian
			const xs = projectSegments(densify(line), vp)
				.flat()
				.map(([x]) => x);
			expect(Math.min(...xs)).toBeLessThan(20);
			expect(Math.max(...xs)).toBeGreaterThan(780);
		}
	});

	it('draws every line whole on a globe as well as a rectangle', () => {
		for (const id of ['equirectangular', 'mollweide', 'orthographic'] as const) {
			const vp = new Viewport(createProjection(id), 400, 400, {
				zoom: 1,
				centerX: 0,
				centerY: 0
			});
			const drawn = graticule(30).filter((line) => pathFor(line, vp) !== '');
			expect(drawn.length, id).toBeGreaterThan(8);
		}
	});
});
