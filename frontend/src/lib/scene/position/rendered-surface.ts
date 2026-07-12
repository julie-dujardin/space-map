import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import {
	fetchHeightBitmap,
	readHeightRows,
	displacementTierUrl
} from '$lib/scene/objects/surface/displacement';
import type { BodyObjects } from '$lib/scene/types';

/** Grid a body's mesh currently renders: a uniform `SphereGeometry`, or the
 *  close-zoom terrain window's explicit row/column angles. */
export type SurfaceGrid =
	| { kind: 'uniform'; segs: number }
	| { kind: 'window'; thetas: Float64Array; phis: Float64Array; key: string };

/** Index i with `arr[i] <= x <= arr[i+1]`, clamped to a valid cell. */
export function cellIndex(arr: Float64Array, x: number): number {
	let lo = 0;
	let hi = arr.length - 2;
	while (lo < hi) {
		const mid = (lo + hi + 1) >> 1;
		if (arr[mid] <= x) lo = mid;
		else hi = mid - 1;
	}
	return lo;
}

/**
 * Displaced ellipsoid point (km) the mesh draws at `latRad`/`lonRad`: the unit
 * normal scaled by the per-axis semi-axes (a,c,b on local x,y,z — see
 * `applyRadiiToMesh`), grown radially by the displacement. Mirrors the vertex
 * shader exactly, so a corner here is the rendered vertex position.
 */
export function displacedPoint(
	latRad: number,
	lonRad: number,
	dispKm: number,
	radiusKm: number,
	a: number,
	b: number,
	c: number
): [number, number, number] {
	const f = (radiusKm + dispKm) / radiusKm;
	const cosLat = Math.cos(latRad);
	const nx = cosLat * Math.cos(lonRad);
	const ny = Math.sin(latRad);
	const nz = -cosLat * Math.sin(lonRad);
	return [f * a * nx, f * c * ny, f * b * nz];
}

export interface GridCell {
	/** TL, TR, BL, BR vertex parameters of the bracketing cell. */
	corners: { latRad: number; lonRad: number }[];
	tx: number;
	ty: number;
}

/** Grid cell bracketing (lat, lon): theta runs from the +Y pole, phi from 0
 *  (body-fixed lng = phi + π), with the fractional in-cell position for the
 *  in-triangle interpolation. */
export function gridCell(grid: SurfaceGrid, latRad: number, lonRad: number): GridCell {
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

/** Unit outward normal of the facet {@link trianglePointKm} seats on — the
 *  rendered slope under a landed probe. Degenerate (pole-pinched) facets fall
 *  back to the radial through TL. */
export function triangleNormalKm(
	pts: [number, number, number][],
	tx: number,
	ty: number
): [number, number, number] {
	const [p0, p1, p2] = tx >= ty ? [pts[0], pts[1], pts[3]] : [pts[0], pts[2], pts[3]];
	const e1 = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
	const e2 = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
	const nx = e1[1] * e2[2] - e1[2] * e2[1];
	const ny = e1[2] * e2[0] - e1[0] * e2[2];
	const nz = e1[0] * e2[1] - e1[1] * e2[0];
	const len = Math.hypot(nx, ny, nz);
	if (len < 1e-12) {
		const r = Math.hypot(p0[0], p0[1], p0[2]);
		return [p0[0] / r, p0[1] / r, p0[2] / r];
	}
	const s = nx * p0[0] + ny * p0[1] + nz * p0[2] < 0 ? -1 / len : 1 / len;
	return [nx * s, ny * s, nz * s];
}

/**
 * Single-channel height rows for synchronous per-frame sampling. Tier-swapped
 * maps are `DataTexture`s whose rows already live CPU-side (v=0 = south first);
 * the initial low tier is an image texture, read back once per body (~2 MB).
 */
interface HeightField {
	data: Uint8Array | Uint8ClampedArray;
	width: number;
	height: number;
	/** Row 0 = south (DataTexture) vs north (canvas readback). */
	bottomUp: boolean;
}

const lowFields = new Map<string, HeightField | 'pending' | 'failed'>();

function heightFieldFor(bo: BodyObjects, bodyId: string): HeightField | null {
	const image = bo.displacementMap?.image as
		| { data?: unknown; width?: number; height?: number }
		| undefined;
	if (!image) return null;
	if (image.data instanceof Uint8Array && image.width && image.height) {
		return { data: image.data, width: image.width, height: image.height, bottomUp: true };
	}
	const cached = lowFields.get(bodyId);
	if (cached && cached !== 'pending' && cached !== 'failed') return cached;
	const meta = bo.displacementMeta;
	if (!cached && meta) {
		lowFields.set(bodyId, 'pending');
		void (async () => {
			const bitmap = await fetchHeightBitmap(displacementTierUrl(meta, 'low'));
			const rows = bitmap && (await readHeightRows(bitmap, 0, bitmap.height - 1));
			if (!bitmap || !rows) {
				// fetchHeightBitmap already logged the cause.
				bitmap?.close();
				lowFields.set(bodyId, 'failed');
				return;
			}
			lowFields.set(bodyId, {
				data: rows,
				width: bitmap.width,
				height: bitmap.height,
				bottomUp: false
			});
			bitmap.close();
		})();
	}
	return null;
}

/** Bilinear height texel (0..1) matching the GPU's sampling (wrap S, clamp T). */
function sampleHeightTexel(hf: HeightField, latRad: number, lonRad: number): number {
	const { data, width: w, height: h } = hf;
	const u = 0.5 + lonRad / (2 * Math.PI);
	const v = 0.5 + latRad / Math.PI;
	const fx = (u - Math.floor(u)) * w - 0.5;
	const fy = (hf.bottomUp ? v : 1 - v) * h - 0.5;
	const x0 = Math.floor(fx);
	const y0 = Math.floor(fy);
	const tx = fx - x0;
	const ty = fy - y0;
	const wrapCol = (x: number) => ((x % w) + w) % w;
	const clampRow = (y: number) => (y < 0 ? 0 : y > h - 1 ? h - 1 : y);
	const c0 = wrapCol(x0);
	const c1 = wrapCol(x0 + 1);
	const r0 = clampRow(y0) * w;
	const r1 = clampRow(y0 + 1) * w;
	const top = data[r0 + c0] * (1 - tx) + data[r0 + c1] * tx;
	const bot = data[r1 + c0] * (1 - tx) + data[r1 + c1] * tx;
	return (top * (1 - ty) + bot * ty) / 255;
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
			}
		})();
	}
	return null;
}

/** Grid the body's mesh renders this frame. */
export function gridForBody(bo: BodyObjects | undefined): SurfaceGrid {
	const tw = bo?.terrainWindow;
	return tw
		? { kind: 'window', thetas: tw.thetas, phis: tw.phis, key: `w${tw.stepLevel}x${tw.texWidth}` }
		: { kind: 'uniform', segs: bo?.currentSegments ?? 128 };
}

/**
 * Distance (km) from the body centre to the rendered surface along `dir`
 * (unit, body-fixed Three-coords) — a ray/plane intersection with the triangle
 * the mesh rasterizes there, sampling the height map the GPU currently
 * displaces with. Exact where a radius-at-(lat,lon) comparison would be metres
 * off on oblate bodies (the ellipsoid's normal parametrization drifts from the
 * ray). Null while the height rows or radii are still loading, or when the ray
 * runs parallel to the facet — callers fall back to a spherical shell.
 */
export function renderedSurfaceRadialKm(
	bo: BodyObjects | undefined,
	bodyId: string,
	radiusKm: number,
	dir: [number, number, number]
): number | null {
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
	const latRad = Math.asin(Math.min(Math.max(dir[1], -1), 1));
	const lonRad = Math.atan2(-dir[2], dir[0]);
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
	// The cell is picked from the normal parametrization — a border mispick is
	// harmless since adjacent triangles share edges.
	const [p0, p1, p2] = tx >= ty ? [pts[0], pts[1], pts[3]] : [pts[0], pts[2], pts[3]];
	const e1 = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
	const e2 = [p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]];
	const nx = e1[1] * e2[2] - e1[2] * e2[1];
	const ny = e1[2] * e2[0] - e1[0] * e2[2];
	const nz = e1[0] * e2[1] - e1[1] * e2[0];
	const denom = dir[0] * nx + dir[1] * ny + dir[2] * nz;
	if (Math.abs(denom) < 1e-12) return null;
	const t = (p0[0] * nx + p0[1] * ny + p0[2] * nz) / denom;
	return t > 0 ? t : null;
}
