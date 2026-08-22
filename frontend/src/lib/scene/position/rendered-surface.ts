import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import {
	bilinearHeightTexel,
	fetchHeightBitmap,
	readHeightRows,
	displacementTierUrl,
	type DisplacementMeta
} from '$lib/scene/objects/surface/displacement';
import type { BodyObjects } from '$lib/scene/types';

/** Grid a body's mesh currently renders: a uniform `SphereGeometry`, or the
 *  close-zoom terrain window's explicit row/column angles. */
type SurfaceGrid =
	| { kind: 'uniform'; segs: number }
	| { kind: 'window'; thetas: Float64Array; phis: Float64Array };

/** Index i with `arr[i] <= x <= arr[i+1]`, clamped to a valid cell. */
function cellIndex(arr: Float64Array, x: number): number {
	let lo = 0;
	let hi = arr.length - 2;
	while (lo < hi) {
		const mid = (lo + hi + 1) >> 1;
		if (arr[mid] <= x) lo = mid;
		else hi = mid - 1;
	}
	return lo;
}

/** Body-fixed unit direction for a lat/lon, IAU convention: +X = prime
 *  meridian, +Y = north pole, −Z = east. Shared by every surface seat so
 *  they agree on one point. */
export function bodyFixedUnit(latRad: number, lonRad: number): [number, number, number] {
	const cosLat = Math.cos(latRad);
	return [cosLat * Math.cos(lonRad), Math.sin(latRad), -cosLat * Math.sin(lonRad)];
}

/** Displaced ellipsoid point (km): unit normal scaled by per-axis semi-axes
 *  (a,c,b on local x,y,z — see `applyRadiiToMesh`), grown radially by the
 *  displacement. Mirrors the vertex shader exactly. */
function displacedPoint(
	latRad: number,
	lonRad: number,
	dispKm: number,
	radiusKm: number,
	a: number,
	b: number,
	c: number
): [number, number, number] {
	const f = (radiusKm + dispKm) / radiusKm;
	const [nx, ny, nz] = bodyFixedUnit(latRad, lonRad);
	return [f * a * nx, f * c * ny, f * b * nz];
}

interface GridCell {
	/** TL, TR, BL, BR vertex parameters of the bracketing cell. */
	corners: { latRad: number; lonRad: number }[];
	tx: number;
	ty: number;
}

/** Grid cell bracketing (lat, lon): theta runs from the +Y pole, phi from 0
 *  (body-fixed lng = phi + π), with the fractional in-cell position for the
 *  in-triangle interpolation. */
function gridCell(grid: SurfaceGrid, latRad: number, lonRad: number): GridCell {
	if (grid.kind === 'uniform') {
		const segs = grid.segs;
		const gy = ((Math.PI / 2 - latRad) * segs) / Math.PI;
		const iy0 = Math.min(Math.max(Math.floor(gy), 0), segs - 1);
		const ty = Math.min(Math.max(gy - iy0, 0), 1);
		const gx = ((lonRad - Math.PI) * segs) / (2 * Math.PI);
		const ix0 = Math.floor(gx);
		const tx = gx - ix0;
		const corners = [
			[iy0, ix0],
			[iy0, ix0 + 1],
			[iy0 + 1, ix0],
			[iy0 + 1, ix0 + 1]
		].map(([iy, ix]) => ({
			latRad: Math.PI / 2 - (Math.min(iy, segs) * Math.PI) / segs,
			lonRad: Math.PI + (ix * 2 * Math.PI) / segs
		}));
		return { corners, tx, ty };
	}
	const { thetas, phis } = grid;
	const theta = Math.PI / 2 - latRad;
	let phi = (lonRad - Math.PI) % (2 * Math.PI);
	if (phi < 0) phi += 2 * Math.PI;
	const iy0 = cellIndex(thetas, theta);
	const ix0 = cellIndex(phis, phi);
	const ty = Math.min(Math.max((theta - thetas[iy0]) / (thetas[iy0 + 1] - thetas[iy0]), 0), 1);
	const tx = Math.min(Math.max((phi - phis[ix0]) / (phis[ix0 + 1] - phis[ix0]), 0), 1);
	const corners = [
		[iy0, ix0],
		[iy0, ix0 + 1],
		[iy0 + 1, ix0],
		[iy0 + 1, ix0 + 1]
	].map(([iy, ix]) => ({
		latRad: Math.PI / 2 - thetas[iy],
		lonRad: phis[ix] + Math.PI
	}));
	return { corners, tx, ty };
}

/** Barycentric on the triangle the mesh draws: both grid builders split each
 *  quad along the TL–BR diagonal ((a,b,d) + (b,c,d) with b=TL, d=BR). */
export function trianglePointKm(
	pts: [number, number, number][],
	tx: number,
	ty: number
): [number, number, number] {
	const [tl, tr, bl, br] = pts;
	const out: [number, number, number] = [0, 0, 0];
	for (let axis = 0; axis < 3; axis++) {
		out[axis] =
			tx >= ty
				? tl[axis] + (tr[axis] - tl[axis]) * tx + (br[axis] - tr[axis]) * ty
				: tl[axis] + (br[axis] - bl[axis]) * tx + (bl[axis] - tl[axis]) * ty;
	}
	return out;
}

/** Vertex and unnormalized cross product of the facet plane at (tx, ty) —
 *  same TL–BR triangle split as {@link trianglePointKm}. */
function facetPlane(
	pts: [number, number, number][],
	tx: number,
	ty: number
): { p0: [number, number, number]; n: [number, number, number] } {
	const [p0, p1, p2] = tx >= ty ? [pts[0], pts[1], pts[3]] : [pts[0], pts[2], pts[3]];
	const e1 = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
	const e2 = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
	return {
		p0,
		n: [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
	};
}

/** Unit outward normal of the facet {@link trianglePointKm} seats on — the
 *  rendered slope under a landed probe. Degenerate (pole-pinched) facets fall
 *  back to the radial through TL. */
export function triangleNormalKm(
	pts: [number, number, number][],
	tx: number,
	ty: number
): [number, number, number] {
	const { p0, n } = facetPlane(pts, tx, ty);
	const len = Math.hypot(n[0], n[1], n[2]);
	if (len < 1e-12) {
		const r = Math.hypot(p0[0], p0[1], p0[2]);
		return [p0[0] / r, p0[1] / r, p0[2] / r];
	}
	const s = n[0] * p0[0] + n[1] * p0[1] + n[2] * p0[2] < 0 ? -1 / len : 1 / len;
	return [n[0] * s, n[1] * s, n[2] * s];
}

/** Single-channel height rows for synchronous per-frame sampling. Tier-swapped
 *  maps are `DataTexture`s, rows already CPU-side (v=0=south); the initial low
 *  tier is an image texture, read back once per body (~2 MB). */
interface HeightField {
	data: Uint8Array | Uint8ClampedArray;
	width: number;
	height: number;
	/** Row 0 = south (DataTexture) vs north (canvas readback). */
	bottomUp: boolean;
}

const lowFields = new Map<string, HeightField | 'failed'>();
const lowFieldLoads = new Map<string, Promise<HeightField | null>>();

/** Bumped when async surface inputs (height rows, radii) resolve. The renderer
 *  watches it to run a position pass while paused — without a jd change nothing
 *  else would re-seat a landed probe on the newly exact surface. */
let dataEpoch = 0;

export function surfaceDataEpoch(): number {
	return dataEpoch;
}

/** Each resident field is ~2 MB; keep the most recently used few instead of
 *  one per DEM body ever visited. Evicted fields reload on demand. */
const MAX_LOW_FIELDS = 6;

function evictLowFields(): void {
	let resident = 0;
	for (const v of lowFields.values()) if (v !== 'failed') resident++;
	for (const [key, v] of lowFields) {
		if (resident <= MAX_LOW_FIELDS) break;
		if (v === 'failed') continue;
		lowFields.delete(key);
		resident--;
	}
}

/** Low-tier readback per body (~2 MB), shared by every sampler. */
function loadLowField(bodyId: string, meta: DisplacementMeta): Promise<HeightField | null> {
	let load = lowFieldLoads.get(bodyId);
	if (load) return load;
	load = (async () => {
		const bitmap = await fetchHeightBitmap(displacementTierUrl(meta, 'low'));
		const rows = bitmap && (await readHeightRows(bitmap, 0, bitmap.height - 1));
		if (!bitmap || !rows) {
			// fetchHeightBitmap already logged the cause.
			bitmap?.close();
			lowFields.set(bodyId, 'failed');
			return null;
		}
		const hf: HeightField = {
			data: rows,
			width: bitmap.width,
			height: bitmap.height,
			bottomUp: false
		};
		bitmap.close();
		lowFields.set(bodyId, hf);
		evictLowFields();
		dataEpoch++;
		return hf;
	})();
	// The entry only dedupes concurrent loads; holding it after settle would
	// pin an evicted field's buffer for the session.
	load.finally(() => lowFieldLoads.delete(bodyId));
	lowFieldLoads.set(bodyId, load);
	return load;
}

function heightFieldFor(bo: BodyObjects, bodyId: string): HeightField | null {
	const image = bo.displacementMap?.image as
		| { data?: unknown; width?: number; height?: number }
		| undefined;
	if (!image) return null;
	if (image.data instanceof Uint8Array && image.width && image.height) {
		return { data: image.data, width: image.width, height: image.height, bottomUp: true };
	}
	const cached = lowFields.get(bodyId);
	if (cached && cached !== 'failed') {
		// Refresh recency (Map iterates in insertion order) so the focused
		// body's field isn't the eviction victim.
		lowFields.delete(bodyId);
		lowFields.set(bodyId, cached);
		return cached;
	}
	const meta = bo.displacementMeta;
	if (!cached && meta) void loadLowField(bodyId, meta);
	return null;
}

/** Bilinear height texel (0..1) matching the GPU's sampling (wrap S, clamp T). */
function sampleHeightTexel(hf: HeightField, latRad: number, lonRad: number): number {
	const u = 0.5 + lonRad / (2 * Math.PI);
	const v = 0.5 + latRad / Math.PI;
	const fx = (u - Math.floor(u)) * hf.width - 0.5;
	const fy = (hf.bottomUp ? v : 1 - v) * hf.height - 0.5;
	return bilinearHeightTexel(hf.data, hf.width, hf.height, fx, fy);
}

/**
 * Displacement (km) at each point, from the same cached height rows the seat
 * and camera-floor samplers read — one readback per body, shared. Prefers the
 * bound tier's CPU-side rows, else awaits the shared low-tier readback (`meta`
 * lets callers sample before the GPU texture attaches). Null if load failed.
 */
export async function displacementsKmAt(
	bo: BodyObjects | undefined,
	bodyId: string,
	meta: DisplacementMeta,
	radiusKm: number,
	points: { latRad: number; lonRad: number }[]
): Promise<Float64Array | null> {
	const hf = (bo && heightFieldFor(bo, bodyId)) ?? (await loadLowField(bodyId, meta));
	if (!hf) return null;
	const biasKm = meta.bias_km - (meta.absolute_radius ? radiusKm : 0);
	const out = new Float64Array(points.length);
	for (let i = 0; i < points.length; i++) {
		out[i] = sampleHeightTexel(hf, points[i].latRad, points[i].lonRad) * meta.scale_km + biasKm;
	}
	return out;
}

const radiiCache = new Map<string, { a: number; b: number; c: number }>();
const radiiPending = new Set<string>();

function radiiFor(bodyId: string, radiusKm: number): { a: number; b: number; c: number } | null {
	const cached = radiiCache.get(bodyId);
	if (cached) return cached;
	if (!radiiPending.has(bodyId)) {
		radiiPending.add(bodyId);
		void (async () => {
			try {
				const global = (await fetchObjectDetail(bodyId, false)).global;
				radiiCache.set(bodyId, global?.radii ?? { a: radiusKm, b: radiusKm, c: radiusKm });
			} catch (err) {
				// Cache the sphere so a persistent failure doesn't refetch every frame.
				console.warn(`Failed to load radii for ${bodyId}:`, err);
				radiiCache.set(bodyId, { a: radiusKm, b: radiusKm, c: radiusKm });
			} finally {
				radiiPending.delete(bodyId);
				dataEpoch++;
			}
		})();
	}
	return null;
}

/** Grid the body's mesh renders this frame. */
function gridForBody(bo: BodyObjects | undefined): SurfaceGrid {
	const tw = bo?.terrainWindow;
	return tw
		? { kind: 'window', thetas: tw.thetas, phis: tw.phis }
		: { kind: 'uniform', segs: bo?.currentSegments ?? 128 };
}

/** Rendered grid cell bracketing (lat, lon): the four displaced vertex
 *  positions (km) the GPU rasterizes this frame, plus in-cell fractions. Null
 *  while height rows/radii are loading. Shared by the landed-probe seat and
 *  camera terrain floor so they never disagree. */
function renderedCell(
	bo: BodyObjects | undefined,
	bodyId: string,
	radiusKm: number,
	latRad: number,
	lonRad: number
): { pts: [number, number, number][]; tx: number; ty: number } | null {
	const radii = radiiFor(bodyId, radiusKm);
	if (!radii) return null;
	let hf: HeightField | null = null;
	let scaleKm = 0;
	let biasKm = 0;
	const meta = bo?.displacementMeta;
	if (meta && bo?.displacementMap) {
		hf = heightFieldFor(bo, bodyId);
		if (!hf) return null;
		scaleKm = meta.scale_km;
		biasKm = meta.bias_km - (meta.absolute_radius ? radiusKm : 0);
	}
	const { corners, tx, ty } = gridCell(gridForBody(bo), latRad, lonRad);
	const pts = corners.map((corner) => {
		const dispKm = hf ? sampleHeightTexel(hf, corner.latRad, corner.lonRad) * scaleKm + biasKm : 0;
		return displacedPoint(
			corner.latRad,
			corner.lonRad,
			dispKm,
			radiusKm,
			radii.a,
			radii.b,
			radii.c
		);
	});
	return { pts, tx, ty };
}

/** Seat for a landed probe: the rendered-triangle point at the record's
 *  (lat, lon) and the facet's unit normal (the probe's up on the slope), in
 *  body-fixed km. Null while surface data loads — caller falls back. */
export function renderedSeatAt(
	bo: BodyObjects | undefined,
	bodyId: string,
	radiusKm: number,
	latRad: number,
	lonRad: number
): { pointKm: [number, number, number]; normal: [number, number, number] } | null {
	const cell = renderedCell(bo, bodyId, radiusKm, latRad, lonRad);
	if (!cell) return null;
	return {
		pointKm: trianglePointKm(cell.pts, cell.tx, cell.ty),
		normal: triangleNormalKm(cell.pts, cell.tx, cell.ty)
	};
}

/**
 * Distance (km) from body centre to the rendered surface along `dir` (unit,
 * body-fixed) — a ray/plane intersection with the facet the GPU rasterizes
 * there. Exact where radius-at-(lat,lon) would be metres off on oblate bodies
 * (the ellipsoid normal drifts from the ray). Null while data is loading, or
 * when the ray runs parallel to the facet — caller falls back to a sphere.
 */
export function renderedSurfaceRadialKm(
	bo: BodyObjects | undefined,
	bodyId: string,
	radiusKm: number,
	dir: [number, number, number]
): number | null {
	const radii = radiiFor(bodyId, radiusKm);
	if (!radii) return null;
	// Parametric coords of the surface point along `dir`: displacement grows
	// points radially, so the crossing keeps the direction of (a·nx, c·ny, b·nz)
	// — invert that, not asin(dir.y). On oblate bodies the geocentric latitude
	// is off by up to ~flattening radians, which at a texel-perfect terrain
	// window picks a facet many cells away and extends its plane far outside
	// its footprint (tens of metres on rough terrain).
	const latRad = Math.atan2(dir[1] / radii.c, Math.hypot(dir[0] / radii.a, dir[2] / radii.b));
	const lonRad = Math.atan2(-dir[2] / radii.b, dir[0] / radii.a);
	const cell = renderedCell(bo, bodyId, radiusKm, latRad, lonRad);
	if (!cell) return null;
	const { p0, n } = facetPlane(cell.pts, cell.tx, cell.ty);
	const denom = dir[0] * n[0] + dir[1] * n[1] + dir[2] * n[2];
	if (Math.abs(denom) < 1e-12) return null;
	const t = (p0[0] * n[0] + p0[1] * n[1] + p0[2] * n[2]) / denom;
	return t > 0 ? t : null;
}
