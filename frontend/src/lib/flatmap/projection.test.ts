import { describe, expect, it } from 'vitest';
import {
	createProjection,
	PROJECTION_IDS,
	projectionAspect,
	wrapLon,
	type Projection,
	type ProjectionId
} from './projection';

/** Places spread over the globe, away from the seams and poles where a
 *  projection is allowed to be ambiguous. */
const PLACES: [number, number][] = [
	[0, 0],
	[12, 48],
	[-74, 41],
	[139, 36],
	[151, -34],
	[-58, -35],
	[37, 56],
	[-1, 51],
	[100, -5],
	[-120, 60]
];

describe('wrapLon', () => {
	it('folds a longitude into −180…180', () => {
		expect(wrapLon(0)).toBe(0);
		expect(wrapLon(190)).toBe(-170);
		expect(wrapLon(-190)).toBe(170);
		expect(wrapLon(540)).toBe(-180);
	});
});

describe.each(PROJECTION_IDS)('%s', (id: ProjectionId) => {
	const projection = createProjection(id);

	it('comes back to where it started', () => {
		for (const [lon, lat] of PLACES) {
			const plane = projection.forward(lon, lat);
			if (!plane) continue; // behind the globe for the azimuthal ones
			const back = projection.inverse(plane[0], plane[1]);
			expect(back, `${id} lost ${lon},${lat}`).not.toBeNull();
			expect(back![0]).toBeCloseTo(lon, 6);
			expect(back![1]).toBeCloseTo(lat, 6);
		}
	});

	it('puts the centre of the map at the origin', () => {
		const centre = projection.azimuthal ? projection.inverse(0, 0) : projection.forward(0, 0);
		expect(centre).not.toBeNull();
		if (!projection.azimuthal) {
			expect(centre![0]).toBeCloseTo(0, 9);
			expect(centre![1]).toBeCloseTo(0, 9);
		}
	});

	it('keeps every mapped point inside the extent', () => {
		const { minX, minY, maxX, maxY } = projection.extent;
		for (let lat = -90; lat <= 90; lat += 5) {
			for (let lon = -180; lon <= 180; lon += 5) {
				const p = projection.forward(lon, lat);
				if (!p) continue;
				expect(p[0]).toBeGreaterThanOrEqual(minX - 1e-9);
				expect(p[0]).toBeLessThanOrEqual(maxX + 1e-9);
				expect(p[1]).toBeGreaterThanOrEqual(minY - 1e-9);
				expect(p[1]).toBeLessThanOrEqual(maxY + 1e-9);
			}
		}
	});

	it('refuses a point well outside its world', () => {
		const { maxX, maxY } = projection.extent;
		expect(projection.inverse(maxX * 4, maxY * 4)).toBeNull();
	});

	it('rotates with the central meridian', () => {
		const turned = createProjection(id, { centerLon: 40, centerLat: 0 });
		const plane = turned.forward(40, 0);
		expect(plane).not.toBeNull();
		expect(plane![0]).toBeCloseTo(0, 9);
	});
});

/**
 * Whether a row of the plane is one parallel with the meridians evenly spread
 * along it — the property that lets the resampling walk resolve a whole row at
 * once, and so the property a `rowInverse` claims.
 */
function rowIsAParallel(projection: Projection): boolean {
	const lon0 = projection.centerLon;
	const points = [-90, -45, 0, 45, 90].map((d) => projection.forward(lon0 + d, 25));
	if (points.some((p) => p === null)) return false;
	const [a, b, c] = points as [number, number][];
	const straight = points.every((p) => Math.abs(p![1] - a[1]) < 1e-9);
	const even = Math.abs(b[0] - a[0] - (c[0] - b[0])) < 1e-9;
	return straight && even;
}

describe.each(PROJECTION_IDS)('%s row inverse', (id: ProjectionId) => {
	// The resampling walk takes this shortcut for every projection that offers
	// one, so it has to agree with the honest answer everywhere.
	const projection = createProjection(id, { centerLon: 25 });

	it('is offered exactly when a row is one parallel evenly divided', () => {
		expect(Boolean(projection.rowInverse)).toBe(rowIsAParallel(projection));
	});

	it('agrees with the pixel-by-pixel inverse, or is absent', () => {
		if (!projection.rowInverse) return;
		const { minX, maxX, minY, maxY } = projection.extent;
		let compared = 0;
		for (let iy = 0; iy <= 40; iy++) {
			const y = minY + ((maxY - minY) * iy) / 40;
			const row = projection.rowInverse(y);
			for (let ix = 0; ix <= 40; ix++) {
				const x = minX + ((maxX - minX) * ix) / 40;
				// The very edge of the row is a tie the two can break differently by
				// a single ulp, so the agreement is asserted either side of it.
				if (row && Math.abs(Math.abs(x) - row.maxAbsX) < 1e-6 * Math.max(1, row.maxAbsX)) {
					continue;
				}
				const point = projection.inverse(x, y);
				const onRow = row !== null && Math.abs(x) < row.maxAbsX;
				if (!point) {
					// Where the row says nothing is, the point must agree.
					expect(onRow, `${id} kept ${x},${y}`).toBe(false);
					continue;
				}
				expect(onRow, `${id} dropped ${x},${y}`).toBe(true);
				compared++;
				expect(row!.lat).toBeCloseTo(point[1], 6);
				const lon = x * row!.lonPerX + projection.centerLon;
				expect(wrapLon(lon)).toBeCloseTo(point[0], 6);
			}
		}
		expect(compared).toBeGreaterThan(100);
	});
});

describe('equirectangular', () => {
	it('is the texture’s own space, degrees scaled to radians', () => {
		const p = createProjection('equirectangular');
		expect(p.forward(180, 90)).toEqual([-Math.PI, Math.PI / 2]);
		expect(p.forward(90, -45)![0]).toBeCloseTo(Math.PI / 2, 12);
		expect(projectionAspect(p)).toBeCloseTo(2, 12);
	});
});

describe('equalEarth', () => {
	it('holds the published shape', () => {
		const p = createProjection('equalEarth');
		// Šavrič, Patterson & Jenny give the frame as 2.05 wide to 1 high.
		expect(projectionAspect(p)).toBeCloseTo(2.05, 2);
		expect(p.forward(0, 90)![1]).toBeCloseTo(1.3172, 3);
		expect(p.forward(179.999, 0)![0]).toBeCloseTo(2.7066, 3);
	});

	it('is equal-area: the same solid angle covers the same plane area', () => {
		// A cell's plane area over the solid angle it subtends should be one
		// constant everywhere — that is what equal-area means.
		const p = createProjection('equalEarth');
		const cellArea = (lon: number, lat: number) => {
			const d = 0.5;
			const a = p.forward(lon, lat)!;
			const b = p.forward(lon + d, lat)!;
			const c = p.forward(lon, lat + d)!;
			// Cross product of the two edges: the cell's area on the plane.
			return Math.abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]));
		};
		const solidAngle = (lat: number) => Math.cos((lat + 0.25) * (Math.PI / 180));
		const ratio = (lon: number, lat: number) => cellArea(lon, lat) / solidAngle(lat);
		const reference = ratio(0, 0);
		for (const [lon, lat] of [
			[60, 45],
			[-120, -60],
			[30, 70],
			[-90, 10]
		]) {
			expect(ratio(lon, lat) / reference).toBeCloseTo(1, 2);
		}
	});
});

describe('mollweide', () => {
	it('is an ellipse twice as wide as it is tall', () => {
		const p = createProjection('mollweide');
		expect(projectionAspect(p)).toBeCloseTo(2, 12);
		expect(p.forward(0, 90)![1]).toBeCloseTo(Math.SQRT2, 9);
		expect(p.forward(179.999, 0)![0]).toBeCloseTo(2 * Math.SQRT2, 4);
	});

	it('leaves the corners of its box off the map', () => {
		const p = createProjection('mollweide');
		expect(p.inverse(2 * Math.SQRT2 - 0.01, Math.SQRT2 - 0.01)).toBeNull();
	});
});

describe('orthographic', () => {
	it('hides the far side of the globe', () => {
		const p = createProjection('orthographic', { centerLon: 0, centerLat: 0 });
		expect(p.forward(0, 0)).toEqual([0, 0]);
		expect(p.forward(180, 0)).toBeNull();
		expect(p.forward(91, 0)).toBeNull();
		expect(p.forward(89, 0)).not.toBeNull();
	});

	it('is a unit disc, and the pole sits at the top when centred on the equator', () => {
		const p = createProjection('orthographic');
		expect(projectionAspect(p)).toBeCloseTo(1, 12);
		expect(p.forward(0, 90)).toEqual([expect.closeTo(0, 12), expect.closeTo(1, 12)]);
		expect(p.inverse(1.5, 0)).toBeNull();
	});

	it('turns to face the centre it is given', () => {
		const p = createProjection('orthographic', { centerLon: -74, centerLat: 41 });
		expect(p.forward(-74, 41)).toEqual([expect.closeTo(0, 12), expect.closeTo(0, 12)]);
		// The antipode is behind it.
		expect(p.forward(106, -41)).toBeNull();
	});
});

describe('stereographic', () => {
	it('is polar by default and reaches past the equator', () => {
		const p = createProjection('stereographic');
		expect(p.forward(0, 90)).toEqual([expect.closeTo(0, 12), expect.closeTo(0, 12)]);
		expect(p.forward(0, 0)).not.toBeNull();
		expect(p.forward(0, -29)).not.toBeNull();
		expect(p.forward(0, -31)).toBeNull();
	});

	it('is conformal: a small cell keeps its shape', () => {
		const p = createProjection('stereographic');
		const d = 0.01;
		for (const [lon, lat] of [
			[0, 60],
			[120, 20],
			[-40, -10]
		]) {
			const a = p.forward(lon, lat)!;
			const east = p.forward(lon + d, lat)!;
			const north = p.forward(lon, lat + d)!;
			// The east step is foreshortened by cos(lat) on the sphere, so scale it
			// back before comparing the two on the plane.
			const dEast = Math.hypot(east[0] - a[0], east[1] - a[1]) / Math.cos(lat * (Math.PI / 180));
			const dNorth = Math.hypot(north[0] - a[0], north[1] - a[1]);
			expect(dEast / dNorth).toBeCloseTo(1, 3);
			// And the two stay at right angles.
			const dot = (east[0] - a[0]) * (north[0] - a[0]) + (east[1] - a[1]) * (north[1] - a[1]);
			expect(dot / (dEast * dNorth)).toBeCloseTo(0, 3);
		}
	});
});

describe('sinusoidal', () => {
	it('is a pointed lens, twice as wide as it is high', () => {
		const p = createProjection('sinusoidal');
		expect(projectionAspect(p)).toBeCloseTo(2, 12);
		// The meridians meet at the poles, so the map has no width there at all.
		expect(p.forward(179.999999, 90)![0]).toBeCloseTo(0, 12);
		expect(p.forward(179.999999, 60)![0]).toBeCloseTo(Math.PI / 2, 6);
	});

	it('is equal-area: a parallel is as short as its circle', () => {
		const p = createProjection('sinusoidal');
		for (const lat of [0, 30, 60, 80]) {
			const width = p.forward(179.999999, lat)![0];
			expect(width / Math.PI).toBeCloseTo(Math.cos(lat * (Math.PI / 180)), 6);
		}
	});
});

describe('robinson', () => {
	it('holds the published frame and table', () => {
		const p = createProjection('robinson');
		expect(projectionAspect(p)).toBeCloseTo(1.9716, 3);
		// The pole is a line, 0.5322 of the equator's length.
		expect(p.forward(179.999999, 90)![0] / p.forward(179.999999, 0)![0]).toBeCloseTo(0.5322, 9);
		expect(p.forward(0, 90)![1]).toBeCloseTo(1.3523, 9);
	});

	it('runs smoothly between the values it was published with', () => {
		const p = createProjection('robinson');
		// The table is given every 5°; a kink at those steps would show on every
		// meridian, so the curve through them has to keep its slope.
		let previous = Infinity;
		for (let lat = 2.5; lat < 90; lat += 2.5) {
			const width = p.forward(90, lat)![0];
			expect(width).toBeLessThan(previous);
			previous = width;
		}
	});
});
