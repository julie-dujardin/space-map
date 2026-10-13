/**
 * The terrain window's grid as numbers, apart from the mesh so that the
 * relief worker can build it and it can be tested.
 *
 * The grid is one lat/lon grid over the whole body, which avoids seams and
 * z-fighting and keeps raycasting and probe seating on one geometry. Around
 * the point under the camera it is cut finer, in bands: each band's cells are
 * twice as wide as those of the band inside it, so a cell looks about as wide
 * from the camera wherever it is. Every row and column sits on a multiple of
 * its own step, and the steps are powers of two of one pixel of the height
 * pyramid: a grid rebuilt around another point has its vertices in the same
 * places, and the ground does not swim.
 */

/** Global grid density outside the window (matches the top sphere-LOD tier). */
export const COARSE_SEGS = 128;

/** Window reach past the horizon: covers peaks visible from beyond it. */
export const MARGIN = 1.25;

/** sin(lat) floor for the longitude half-width; keeps polar windows bounded. */
export const SIN_FLOOR = 0.05;

/** Width of the pyramid's coarsest level, in pixels. */
const BASE_WIDTH_PX = 2048;

export interface GridAxis {
	/** Angles of the rows or columns, ascending, both ends of the axis included. */
	at: Float64Array;
	/** Per angle: the pyramid level whose pixels are as wide as the cells there. */
	level: Int8Array;
}

export interface NestedGrid {
	/** Rows, as angles θ from the +Y pole (0..π). */
	rows: GridAxis;
	/** Columns, as angles φ (0..2π, the seam at both ends). */
	columns: GridAxis;
	/** The finest cells are `2^stepLevel` pixels of the finest level wide. */
	stepLevel: number;
	/** Angle from the centre to the edge of the finest band. */
	innerRadius: number;
}

interface Band {
	intervals: [number, number][];
	step: number;
	level: number;
}

/**
 * One axis: the coarse grid, with the points of each band in place of it over
 * that band's intervals. `bands` are finest first, each inside the next.
 */
function mergeBands(max: number, bands: Band[], coarseStep: number): GridAxis {
	const inside = (band: Band | undefined, p: number) =>
		!!band && band.intervals.some(([lo, hi]) => p > lo + 1e-9 && p < hi - 1e-9);
	const points: { p: number; level: number }[] = [];
	const segments = Math.round(max / coarseStep);
	for (let j = 0; j <= segments; j++) {
		const p = j === segments ? max : j * coarseStep;
		if (j === 0 || j === segments || !inside(bands[bands.length - 1], p)) {
			points.push({ p, level: 0 });
		}
	}
	bands.forEach((band, i) => {
		for (const [lo, hi] of band.intervals) {
			const n0 = Math.ceil(Math.max(lo, 0) / band.step - 1e-9);
			const n1 = Math.floor(Math.min(hi, max) / band.step + 1e-9);
			for (let n = n0; n <= n1; n++) {
				const p = n * band.step;
				if (!inside(bands[i - 1], p)) points.push({ p, level: band.level });
			}
		}
	});
	points.sort((a, b) => a.p - b.p || b.level - a.level);
	// Two bands share the points on the line between them.
	const tolerance = (bands[0]?.step ?? coarseStep) * 0.25;
	const kept: { p: number; level: number }[] = [];
	for (const point of points) {
		const last = kept[kept.length - 1];
		if (last && point.p - last.p < tolerance) last.level = Math.max(last.level, point.level);
		else kept.push(point);
	}
	// A point within the tolerance of an end takes the end's place.
	kept[0].p = 0;
	kept[kept.length - 1].p = max;
	return {
		at: Float64Array.from(kept, (point) => point.p),
		level: Int8Array.from(kept, (point) => point.level)
	};
}

/** `[centre − half, centre + half]` on a circle of `2π`, cut at the seam. */
function arcIntervals(centre: number, half: number): [number, number][] {
	const full = 2 * Math.PI;
	if (half >= Math.PI) return [[0, full]];
	const lo = centre - half;
	const hi = centre + half;
	if (lo < 0)
		return [
			[0, hi],
			[lo + full, full]
		];
	if (hi > full)
		return [
			[0, hi - full],
			[lo, full]
		];
	return [[lo, hi]];
}

/** Angle that one pixel of the finest level of a pyramid spans on the map. */
function finestPixel(maxLevel: number): number {
	return (2 * Math.PI) / (BASE_WIDTH_PX * 2 ** maxLevel);
}

/**
 * How wide the finest cells are for a camera at `altitude` above the mean
 * sphere, in body radii: `2^level` pixels of the pyramid's finest level. The
 * finest band then reaches as far out as the camera is high, and its cells
 * look as wide from there as those of the bands around it. `previous` is the
 * level of the grid in place, kept near the line between two.
 */
export function nestedStepLevel(
	altitude: number,
	maxLevel: number,
	bandCells: number,
	previous?: number
): number {
	const pixel = finestPixel(maxLevel);
	const raw = Math.log2(Math.max(altitude / bandCells, pixel) / pixel);
	if (previous !== undefined && raw > previous - 0.85 && raw < previous + 0.15) return previous;
	return Math.max(0, Math.ceil(raw - 1e-9));
}

/**
 * The grid for a camera over `(centreTheta, centrePhi)` at `altitude` above
 * the mean sphere, in body radii. `peak` is how far the relief stands above
 * the sphere, in radii: ground that high shows from beyond the horizon.
 * `bandCells` is the cells from one band's edge to the next, and `stepLevel`
 * what `nestedStepLevel` gave.
 */
export function planNestedGrid(
	centreTheta: number,
	centrePhi: number,
	altitude: number,
	peak: number,
	maxLevel: number,
	bandCells: number,
	stepLevel: number
): NestedGrid {
	const pixel = finestPixel(maxLevel);

	const rowStep = Math.PI / COARSE_SEGS;
	const columnStep = (2 * Math.PI) / COARSE_SEGS;
	const horizon = (height: number) => Math.acos(1 / (1 + Math.max(height, 0)));
	const reach = MARGIN * (horizon(altitude) + horizon(peak));
	const sinTheta = Math.max(Math.sin(centreTheta), SIN_FLOOR);
	// A column is narrower on the ground than a row by sin θ.
	const widen = Math.round(Math.log2(1 / sinTheta));

	const rowBands: Band[] = [];
	const columnBands: Band[] = [];
	let radius = 0;
	for (let exponent = stepLevel; radius < reach; exponent++) {
		const step = pixel * 2 ** exponent;
		if (step >= rowStep) break;
		radius += bandCells * step;
		const level = Math.max(maxLevel - exponent, 0);
		rowBands.push({
			intervals: [[Math.max(centreTheta - radius, 0), Math.min(centreTheta + radius, Math.PI)]],
			step,
			level
		});
		// Near a pole a band goes all the way round: its columns are then as
		// many as its rows, however narrow that makes them at the pole.
		const half = Math.min(radius / sinTheta, Math.PI);
		const fit = Math.ceil(Math.log2((2 * half) / (4 * bandCells) / pixel) - 1e-9);
		const columnExponent = Math.max(exponent + widen, fit);
		const columnWidth = pixel * 2 ** columnExponent;
		if (columnWidth >= columnStep) continue;
		columnBands.push({
			intervals: arcIntervals(centrePhi, half),
			step: columnWidth,
			level: Math.max(maxLevel - (columnExponent - widen), 0)
		});
	}

	return {
		rows: mergeBands(Math.PI, rowBands, rowStep),
		columns: mergeBands(2 * Math.PI, columnBands, columnStep),
		stepLevel,
		innerRadius: bandCells * pixel * 2 ** stepLevel
	};
}

export interface GridArrays {
	positions: Float32Array;
	normals: Float32Array;
	uvs: Float32Array;
	indices: Uint32Array;
}

/**
 * Vertices and triangles of a lat/lon grid that mirrors `SphereGeometry`'s
 * parametrization, so maps, self-shadow and probe-triangle interpolation
 * carry over unchanged. `riseKm`, when given, is each vertex's height above
 * the sphere of `radius`, row by row, and `unitsPerKm` puts it in the units
 * of `radius`.
 */
export function buildGridArrays(
	radius: number,
	thetas: Float64Array,
	phis: Float64Array,
	riseKm?: Float32Array,
	unitsPerKm = 1
): GridArrays {
	const rows = thetas.length;
	const cols = phis.length;
	const positions = new Float32Array(rows * cols * 3);
	const normals = new Float32Array(rows * cols * 3);
	const uvs = new Float32Array(rows * cols * 2);
	const sinPhi = Float64Array.from(phis, Math.sin);
	const cosPhi = Float64Array.from(phis, Math.cos);
	for (let iy = 0; iy < rows; iy++) {
		const theta = thetas[iy];
		const sinT = Math.sin(theta);
		const cosT = Math.cos(theta);
		for (let ix = 0; ix < cols; ix++) {
			const vertex = iy * cols + ix;
			const nx = -cosPhi[ix] * sinT;
			const ny = cosT;
			const nz = sinPhi[ix] * sinT;
			const r = radius + (riseKm ? riseKm[vertex] * unitsPerKm : 0);
			const i3 = vertex * 3;
			positions[i3] = r * nx;
			positions[i3 + 1] = r * ny;
			positions[i3 + 2] = r * nz;
			normals[i3] = nx;
			normals[i3 + 1] = ny;
			normals[i3 + 2] = nz;
			const i2 = vertex * 2;
			uvs[i2] = phis[ix] / (2 * Math.PI);
			uvs[i2 + 1] = 1 - theta / Math.PI;
		}
	}
	const indices = new Uint32Array((rows - 1) * (cols - 1) * 6);
	let k = 0;
	for (let iy = 0; iy < rows - 1; iy++) {
		const topPole = thetas[iy] <= 0;
		const bottomPole = thetas[iy + 1] >= Math.PI;
		for (let ix = 0; ix < cols - 1; ix++) {
			const a = iy * cols + ix + 1;
			const b = iy * cols + ix;
			const c = (iy + 1) * cols + ix;
			const d = (iy + 1) * cols + ix + 1;
			if (!topPole) {
				indices[k++] = a;
				indices[k++] = b;
				indices[k++] = d;
			}
			if (!bottomPole) {
				indices[k++] = b;
				indices[k++] = c;
				indices[k++] = d;
			}
		}
	}
	return { positions, normals, uvs, indices: indices.subarray(0, k) };
}
