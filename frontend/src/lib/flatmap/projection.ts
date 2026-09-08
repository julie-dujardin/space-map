/**
 * Projections for the flat map: degrees of longitude and latitude onto a
 * plane, and back. Each one is a pure pair of functions plus the extent its
 * world fills. The view, the raster warp and the vector overlay are all
 * written against that shape, so a new projection needs nothing but a new
 * entry here.
 *
 * Longitude is east-positive and latitude is north-positive, matching the IAU
 * planetographic convention the export uses.
 */

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

export type ProjectionId =
	| 'equirectangular'
	| 'equalEarth'
	| 'mollweide'
	| 'sinusoidal'
	| 'robinson'
	| 'orthographic'
	| 'stereographic';

/** Offered in this order: the texture's own space first, then the three that
 *  keep area honest, then the one that trades a little of everything for a
 *  familiar shape, then the two that show a globe rather than a rectangle. */
export const PROJECTION_IDS: readonly ProjectionId[] = [
	'equirectangular',
	'equalEarth',
	'mollweide',
	'sinusoidal',
	'robinson',
	'orthographic',
	'stereographic'
];

export interface ProjectionOptions {
	/** Meridian down the middle of the map. */
	centerLon?: number;
	/** Parallel at the middle. Azimuthal projections only — the cylindrical and
	 *  pseudocylindrical ones are always centred on the equator. */
	centerLat?: number;
	/** Degrees from the centre past which the map is blank. Azimuthal only;
	 *  ignored elsewhere, where the whole world always fits. */
	clipAngle?: number;
}

export interface Extent {
	minX: number;
	minY: number;
	maxX: number;
	maxY: number;
}

/**
 * A whole row of the plane resolved at once, for the projections where that is
 * possible: on a cylindrical or pseudocylindrical map every point of a row
 * lies on one parallel, and longitude runs linearly across it.
 *
 * That turns the resampling walk from one inverse projection per pixel into
 * one per row plus a multiply, which is most of what the flat map costs.
 */
export interface ProjectionRow {
	/** The parallel this row of the plane falls on. */
	lat: number;
	/** Degrees of longitude per unit of abscissa, from the central meridian. */
	lonPerX: number;
	/** Abscissa past which the row leaves the map — half the world's width at
	 *  this latitude, which narrows toward the poles on a pointed projection. */
	maxAbsX: number;
}

export interface Projection {
	readonly id: ProjectionId;
	/** Meridian down the middle of the map. */
	readonly centerLon: number;
	/** True when the map repeats east–west, so panning wraps and a shape near
	 *  the seam is drawn on both sides. */
	readonly cyclic: boolean;
	/** True when the world is a disc rather than a rectangle: the corners of the
	 *  extent are outside the map, and a point can be hidden behind the globe. */
	readonly azimuthal: boolean;
	readonly extent: Extent;
	/** Plane coordinates, or null where the place is not on the map. */
	forward(lon: number, lat: number): [number, number] | null;
	/** Longitude and latitude, or null where the plane point is off the world. */
	inverse(x: number, y: number): [number, number] | null;
	/** The whole row at `y` at once, or null where no part of it is on the map.
	 *  Only the projections that map a row to a single parallel have one; the
	 *  two that show a globe do not, and are resampled pixel by pixel. */
	rowInverse?(y: number): ProjectionRow | null;
}

/** Longitude folded into −180…180, so a difference across the seam is the short
 *  way round rather than the long one. */
export function wrapLon(lon: number): number {
	const wrapped = (((lon + 180) % 360) + 360) % 360;
	return wrapped - 180;
}

/** Width over height of the whole world, for sizing a frame that holds it. */
export function projectionAspect(projection: Projection): number {
	const { minX, maxX, minY, maxY } = projection.extent;
	return (maxX - minX) / (maxY - minY);
}

/** Bounding box of everything the projection maps, found by walking a grid.
 *  Sampling rather than algebra keeps a projection's entry to its formulas —
 *  half-degree steps put the error well below a pixel at any size we draw.
 *
 *  The seam is sampled just short of ±180: exactly 180 folds to −180, which
 *  would leave the eastern edge unmeasured and the extent lopsided. */
function sampledExtent(forward: Projection['forward']): Extent {
	let minX = Infinity;
	let minY = Infinity;
	let maxX = -Infinity;
	let maxY = -Infinity;
	const STEPS = 720;
	const EDGE = 180 - 1e-9;
	for (let i = 0; i <= STEPS; i++) {
		const lat = -90 + (180 * i) / STEPS;
		for (let j = 0; j <= STEPS; j++) {
			const p = forward(-EDGE + (2 * EDGE * j) / STEPS, lat);
			if (!p) continue;
			if (p[0] < minX) minX = p[0];
			if (p[0] > maxX) maxX = p[0];
			if (p[1] < minY) minY = p[1];
			if (p[1] > maxY) maxY = p[1];
		}
	}
	return { minX, minY, maxX, maxY };
}

// -- cylindrical ------------------------------------------------------------

function equirectangular(options: ProjectionOptions): Projection {
	const lon0 = options.centerLon ?? 0;
	return {
		id: 'equirectangular',
		centerLon: lon0,
		cyclic: true,
		azimuthal: false,
		extent: { minX: -Math.PI, minY: -Math.PI / 2, maxX: Math.PI, maxY: Math.PI / 2 },
		forward: (lon, lat) => [wrapLon(lon - lon0) * DEG, lat * DEG],
		inverse: (x, y) => {
			// Bounded on both axes: past the seam the plane is off the world, not
			// round it again, or a click beside the map would report a place.
			if (Math.abs(y) > Math.PI / 2 || Math.abs(x) > Math.PI) return null;
			return [wrapLon(x * RAD + lon0), y * RAD];
		},
		rowInverse: (y) => {
			if (Math.abs(y) > Math.PI / 2) return null;
			return { lat: y * RAD, lonPerX: RAD, maxAbsX: Math.PI };
		}
	};
}

// -- pseudocylindrical ------------------------------------------------------

// Equal Earth (Šavrič, Patterson & Jenny 2018): equal-area, and the shape the
// campaign to retire Mercator put in front of the UN.
const EE_A1 = 1.340264;
const EE_A2 = -0.081106;
const EE_A3 = 0.000893;
const EE_A4 = 0.003796;
const EE_SQRT3 = Math.sqrt(3);

/** The polynomial in θ that Equal Earth's ordinate is, and its derivative —
 *  the forward uses the derivative for the abscissa, the inverse for Newton. */
const eeY = (t: number) => EE_A4 * t ** 9 + EE_A3 * t ** 7 + EE_A2 * t ** 3 + EE_A1 * t;
const eeDy = (t: number) => 9 * EE_A4 * t ** 8 + 7 * EE_A3 * t ** 6 + 3 * EE_A2 * t ** 2 + EE_A1;

function equalEarth(options: ProjectionOptions): Projection {
	const lon0 = options.centerLon ?? 0;
	const forward = (lon: number, lat: number): [number, number] | null => {
		const theta = Math.asin(clamp1((EE_SQRT3 / 2) * Math.sin(lat * DEG)));
		const dl = wrapLon(lon - lon0) * DEG;
		return [(2 * EE_SQRT3 * dl * Math.cos(theta)) / (3 * eeDy(theta)), eeY(theta)];
	};
	/** Newton from the ordinate itself: the polynomial is close to linear over
	 *  the range, so this lands inside a float ulp in a few passes. */
	const thetaFor = (y: number): number => {
		let theta = y;
		for (let i = 0; i < 12; i++) {
			const step = (eeY(theta) - y) / eeDy(theta);
			theta -= step;
			if (Math.abs(step) < 1e-12) break;
		}
		return theta;
	};
	return {
		id: 'equalEarth',
		centerLon: lon0,
		cyclic: true,
		azimuthal: false,
		extent: sampledExtent(forward),
		forward,
		rowInverse: (y) => {
			const theta = thetaFor(y);
			const sinLat = (2 / EE_SQRT3) * Math.sin(theta);
			if (Math.abs(sinLat) > 1) return null;
			const lonPerX = ((3 * eeDy(theta)) / (2 * EE_SQRT3 * Math.cos(theta))) * RAD;
			return { lat: Math.asin(sinLat) * RAD, lonPerX, maxAbsX: 180 / lonPerX };
		},
		inverse: (x, y) => {
			const theta = thetaFor(y);
			const sinLat = (2 / EE_SQRT3) * Math.sin(theta);
			if (Math.abs(sinLat) > 1) return null;
			const dl = (3 * eeDy(theta) * x) / (2 * EE_SQRT3 * Math.cos(theta));
			if (Math.abs(dl) > Math.PI) return null;
			return [wrapLon(dl * RAD + lon0), Math.asin(sinLat) * RAD];
		}
	};
}

const MW_SQRT2 = Math.SQRT2;

function mollweide(options: ProjectionOptions): Projection {
	const lon0 = options.centerLon ?? 0;
	return {
		id: 'mollweide',
		centerLon: lon0,
		cyclic: true,
		azimuthal: false,
		extent: { minX: -2 * MW_SQRT2, minY: -MW_SQRT2, maxX: 2 * MW_SQRT2, maxY: MW_SQRT2 },
		forward: (lon, lat) => {
			const phi = lat * DEG;
			// 2θ + sin 2θ = π sin φ, by Newton. The derivative vanishes at the
			// poles, so those are taken directly rather than iterated toward.
			let theta = phi;
			if (Math.abs(Math.abs(phi) - Math.PI / 2) < 1e-9) {
				theta = Math.sign(phi) * (Math.PI / 2);
			} else {
				const target = Math.PI * Math.sin(phi);
				for (let i = 0; i < 20; i++) {
					const step = (2 * theta + Math.sin(2 * theta) - target) / (2 + 2 * Math.cos(2 * theta));
					theta -= step;
					if (Math.abs(step) < 1e-12) break;
				}
			}
			const dl = wrapLon(lon - lon0) * DEG;
			return [((2 * MW_SQRT2) / Math.PI) * dl * Math.cos(theta), MW_SQRT2 * Math.sin(theta)];
		},
		rowInverse: (y) => {
			const sinTheta = y / MW_SQRT2;
			if (Math.abs(sinTheta) > 1) return null;
			const theta = Math.asin(sinTheta);
			const sinLat = (2 * theta + Math.sin(2 * theta)) / Math.PI;
			if (Math.abs(sinLat) > 1) return null;
			const cosTheta = Math.cos(theta);
			// The ellipse closes to a point at the poles: the row is one place
			// wide, and every longitude meets there.
			if (cosTheta < 1e-12) return { lat: Math.sign(y) * 90, lonPerX: 0, maxAbsX: 0 };
			const lonPerX = (Math.PI / (2 * MW_SQRT2 * cosTheta)) * RAD;
			return { lat: Math.asin(sinLat) * RAD, lonPerX, maxAbsX: 180 / lonPerX };
		},
		inverse: (x, y) => {
			const sinTheta = y / MW_SQRT2;
			if (Math.abs(sinTheta) > 1) return null;
			const theta = Math.asin(sinTheta);
			const sinLat = (2 * theta + Math.sin(2 * theta)) / Math.PI;
			if (Math.abs(sinLat) > 1) return null;
			const cosTheta = Math.cos(theta);
			// The ellipse closes to a point at the poles; every x but zero is
			// outside it there.
			if (cosTheta < 1e-12) return Math.abs(x) < 1e-9 ? [lon0, Math.sign(y) * 90] : null;
			const dl = (Math.PI * x) / (2 * MW_SQRT2 * cosTheta);
			if (Math.abs(dl) > Math.PI) return null;
			return [wrapLon(dl * RAD + lon0), Math.asin(sinLat) * RAD];
		}
	};
}

function sinusoidal(options: ProjectionOptions): Projection {
	const lon0 = options.centerLon ?? 0;
	return {
		id: 'sinusoidal',
		centerLon: lon0,
		cyclic: true,
		azimuthal: false,
		extent: { minX: -Math.PI, minY: -Math.PI / 2, maxX: Math.PI, maxY: Math.PI / 2 },
		forward: (lon, lat) => {
			const phi = lat * DEG;
			return [wrapLon(lon - lon0) * DEG * Math.cos(phi), phi];
		},
		rowInverse: (y) => {
			if (Math.abs(y) > Math.PI / 2) return null;
			const cosLat = Math.cos(y);
			// The lens closes to a point at the poles: the row is one place wide,
			// and every longitude meets there.
			if (cosLat < 1e-12) return { lat: Math.sign(y) * 90, lonPerX: 0, maxAbsX: 0 };
			return { lat: y * RAD, lonPerX: RAD / cosLat, maxAbsX: Math.PI * cosLat };
		},
		inverse: (x, y) => {
			if (Math.abs(y) > Math.PI / 2) return null;
			const cosLat = Math.cos(y);
			if (cosLat < 1e-12) return Math.abs(x) < 1e-9 ? [lon0, Math.sign(y) * 90] : null;
			const dl = (x * RAD) / cosLat;
			if (Math.abs(dl) > 180) return null;
			return [wrapLon(dl + lon0), y * RAD];
		}
	};
}

// Robinson (1963): neither equal-area nor conformal, drawn by eye to look
// right. It carried National Geographic's world map from 1988 to 1998 and
// still reads as "the map" to most people.
//
// The projection is a published table and nothing else: the length of every
// parallel and its distance from the equator, both relative, at 5° steps.
const ROBINSON_LENGTH = [
	1.0, 0.9986, 0.9954, 0.99, 0.9822, 0.973, 0.96, 0.9427, 0.9216, 0.8962, 0.8679, 0.835, 0.7986,
	0.7597, 0.7186, 0.6732, 0.6213, 0.5722, 0.5322
];
const ROBINSON_HEIGHT = [
	0.0, 0.062, 0.124, 0.186, 0.248, 0.31, 0.372, 0.434, 0.4958, 0.5571, 0.6176, 0.6769, 0.7346,
	0.7903, 0.8435, 0.8936, 0.9394, 0.9761, 1.0
];
/** Robinson's own scale factors, which set the frame at 1.97 wide to 1 high. */
const ROBINSON_KX = 0.8487;
const ROBINSON_KY = 1.3523;
const ROBINSON_STEP = 5;

type Cubic = [number, number, number, number];

/** A cubic through four consecutive table values, in the fraction along the
 *  middle interval. Catmull–Rom: it passes through every published value and
 *  its slope carries across them, so the meridians come out smooth. */
function splineSegment(table: readonly number[], i: number): Cubic {
	const p0 = table[Math.max(i - 1, 0)];
	const p1 = table[i];
	const p2 = table[i + 1];
	const p3 = table[Math.min(i + 2, table.length - 1)];
	return [
		p1,
		0.5 * (p2 - p0),
		0.5 * (2 * p0 - 5 * p1 + 4 * p2 - p3),
		0.5 * (-p0 + 3 * p1 - 3 * p2 + p3)
	];
}

const splineAt = (c: Cubic, f: number): number => c[0] + f * (c[1] + f * (c[2] + f * c[3]));
const splineSlope = (c: Cubic, f: number): number => c[1] + f * (2 * c[2] + 3 * c[3] * f);

/** The interval of the table a latitude falls in, and how far into it. */
function robinsonSegment(t: number): [number, number] {
	const i = Math.min(Math.max(Math.floor(t), 0), ROBINSON_LENGTH.length - 2);
	return [i, t - i];
}

/** Half the width of the map at a parallel, in plane units. */
function robinsonHalfWidth(t: number): number {
	const [i, f] = robinsonSegment(t);
	return ROBINSON_KX * splineAt(splineSegment(ROBINSON_LENGTH, i), f) * Math.PI;
}

/** The table read backwards: which parallel sits a given relative distance
 *  from the equator. Height climbs steadily, so bracketing the interval and
 *  then running Newton inside it settles in a couple of passes. */
function robinsonHeightToT(h: number): number {
	let lo = 0;
	let hi = ROBINSON_HEIGHT.length - 1;
	while (hi - lo > 1) {
		const mid = (lo + hi) >> 1;
		if (ROBINSON_HEIGHT[mid] <= h) lo = mid;
		else hi = mid;
	}
	const i = Math.min(lo, ROBINSON_HEIGHT.length - 2);
	const c = splineSegment(ROBINSON_HEIGHT, i);
	let f = (h - ROBINSON_HEIGHT[i]) / (ROBINSON_HEIGHT[i + 1] - ROBINSON_HEIGHT[i]);
	for (let n = 0; n < 8; n++) {
		const slope = splineSlope(c, f);
		if (slope === 0) break;
		const step = (splineAt(c, f) - h) / slope;
		f -= step;
		if (Math.abs(step) < 1e-14) break;
	}
	return i + Math.min(Math.max(f, 0), 1);
}

function robinson(options: ProjectionOptions): Projection {
	const lon0 = options.centerLon ?? 0;
	return {
		id: 'robinson',
		centerLon: lon0,
		cyclic: true,
		azimuthal: false,
		extent: {
			minX: -ROBINSON_KX * Math.PI,
			minY: -ROBINSON_KY,
			maxX: ROBINSON_KX * Math.PI,
			maxY: ROBINSON_KY
		},
		forward: (lon, lat) => {
			const [i, f] = robinsonSegment(Math.abs(lat) / ROBINSON_STEP);
			const length = splineAt(splineSegment(ROBINSON_LENGTH, i), f);
			const height = splineAt(splineSegment(ROBINSON_HEIGHT, i), f);
			return [
				ROBINSON_KX * length * wrapLon(lon - lon0) * DEG,
				ROBINSON_KY * height * Math.sign(lat)
			];
		},
		rowInverse: (y) => {
			const h = Math.abs(y) / ROBINSON_KY;
			if (h > 1) return null;
			const t = robinsonHeightToT(h);
			const maxAbsX = robinsonHalfWidth(t);
			return { lat: Math.sign(y) * t * ROBINSON_STEP, lonPerX: 180 / maxAbsX, maxAbsX };
		},
		inverse: (x, y) => {
			const h = Math.abs(y) / ROBINSON_KY;
			if (h > 1) return null;
			const t = robinsonHeightToT(h);
			const dl = (x * 180) / robinsonHalfWidth(t);
			if (Math.abs(dl) > 180) return null;
			return [wrapLon(dl + lon0), Math.sign(y) * t * ROBINSON_STEP];
		}
	};
}

// -- azimuthal --------------------------------------------------------------

function clamp1(v: number): number {
	return v < -1 ? -1 : v > 1 ? 1 : v;
}

/**
 * Longitude and latitude for a point on an azimuthal plane, given how far from
 * the centre it lies. Orthographic and stereographic differ only in the
 * relation between that distance and the angle, so they share this.
 */
function azimuthalInverse(
	x: number,
	y: number,
	rho: number,
	c: number,
	lon0: number,
	phi0: number
): [number, number] {
	if (rho < 1e-12) return [lon0, phi0 * RAD];
	const sinC = Math.sin(c);
	const cosC = Math.cos(c);
	const lat = Math.asin(clamp1(cosC * Math.sin(phi0) + (y * sinC * Math.cos(phi0)) / rho));
	const lon =
		lon0 + Math.atan2(x * sinC, rho * cosC * Math.cos(phi0) - y * sinC * Math.sin(phi0)) * RAD;
	return [wrapLon(lon), lat * RAD];
}

/** Disc extent for an azimuthal projection of radius `r`. */
function discExtent(r: number): Extent {
	return { minX: -r, minY: -r, maxX: r, maxY: r };
}

function orthographic(options: ProjectionOptions): Projection {
	const lon0 = options.centerLon ?? 0;
	const phi0 = (options.centerLat ?? 0) * DEG;
	// Half the globe is all there is to see; a smaller angle crops it further.
	const clip = Math.min(options.clipAngle ?? 90, 90) * DEG;
	const cosClip = Math.cos(clip);
	const radius = Math.sin(clip);
	return {
		id: 'orthographic',
		centerLon: lon0,
		cyclic: false,
		azimuthal: true,
		extent: discExtent(radius),
		forward: (lon, lat) => {
			const dl = wrapLon(lon - lon0) * DEG;
			const phi = lat * DEG;
			const cosC = Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(dl);
			if (cosC < cosClip) return null;
			return [
				Math.cos(phi) * Math.sin(dl),
				Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(dl)
			];
		},
		inverse: (x, y) => {
			const rho = Math.hypot(x, y);
			if (rho > radius) return null;
			return azimuthalInverse(x, y, rho, Math.asin(clamp1(rho)), lon0, phi0);
		}
	};
}

/** How far past the centre a stereographic map reaches by default: enough to
 *  carry the far hemisphere's edge, where a plain hemisphere would cut the
 *  world in half. */
const STEREOGRAPHIC_CLIP = 120;

function stereographic(options: ProjectionOptions): Projection {
	const lon0 = options.centerLon ?? 0;
	// Polar by default — the pole is the point of a stereographic map here, and
	// it is what makes the ice caps and the polar charts legible.
	const phi0 = (options.centerLat ?? 90) * DEG;
	// The antipode is infinitely far away, so the clip must stay short of it.
	const clip = Math.min(options.clipAngle ?? STEREOGRAPHIC_CLIP, 170) * DEG;
	const cosClip = Math.cos(clip);
	const radius = 2 * Math.tan(clip / 2);
	return {
		id: 'stereographic',
		centerLon: lon0,
		cyclic: false,
		azimuthal: true,
		extent: discExtent(radius),
		forward: (lon, lat) => {
			const dl = wrapLon(lon - lon0) * DEG;
			const phi = lat * DEG;
			const cosC = Math.sin(phi0) * Math.sin(phi) + Math.cos(phi0) * Math.cos(phi) * Math.cos(dl);
			if (cosC < cosClip) return null;
			const k = 2 / (1 + cosC);
			return [
				k * Math.cos(phi) * Math.sin(dl),
				k * (Math.cos(phi0) * Math.sin(phi) - Math.sin(phi0) * Math.cos(phi) * Math.cos(dl))
			];
		},
		inverse: (x, y) => {
			const rho = Math.hypot(x, y);
			if (rho > radius) return null;
			return azimuthalInverse(x, y, rho, 2 * Math.atan(rho / 2), lon0, phi0);
		}
	};
}

const BUILDERS: Record<ProjectionId, (options: ProjectionOptions) => Projection> = {
	equirectangular,
	equalEarth,
	mollweide,
	sinusoidal,
	robinson,
	orthographic,
	stereographic
};

/** Build a projection. The result is immutable — turning the globe or moving
 *  the central meridian means building another one, which costs nothing but
 *  the extent sampling. */
export function createProjection(id: ProjectionId, options: ProjectionOptions = {}): Projection {
	const build = BUILDERS[id];
	if (!build) throw new Error(`spacemap: unknown projection "${id}"`);
	return build(options);
}
