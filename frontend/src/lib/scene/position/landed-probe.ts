import { Vector3 } from 'three';
import type { BodyData } from '$lib/types/objects';
import type { LandedRecord, Probe } from '$lib/fetch/position/probes/parse';
import { landedPositionAt } from '$lib/fetch/position/probes/propagate';
import { kmToScene, sceneToKm } from '$lib/math/units';
import { bodyQuaternion } from '$lib/math/orientation';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { sampleDisplacementOffsets } from '$lib/scene/objects/surface/displacement';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { BodyObjects } from '$lib/scene/types';
import type { Vec3 } from '$lib/scene/animation/math';

/**
 * Body-fixed surface seat (km, pre-orientation) per landed probe, keyed by the
 * exact rendering configuration it was computed for. The mesh renders as flat
 * triangles between grid vertices, and each facet's chord dips below the smooth
 * ellipsoid, so seating on the analytic surface left the probe floating. We
 * instead sample the four grid vertices bracketing the probe and interpolate
 * over the triangle the GPU rasterizes — a bilinear blend deviates from it by
 * metres on twisted quads (rover-height at Gale). Recomputed when the grid
 * (sphere-LOD segments or terrain-window step) or displacement tier changes;
 * the record's altitude is unused (coarse height maps make it float/sink).
 * Absent until first resolved (probe rests on the mean-radius sphere meanwhile).
 */
const surfacePointKm = new Map<string, [number, number, number]>();
const surfacePointKey = new Map<string, string>();
const surfacePointPending = new Set<string>();

/** Grid the landing body's mesh currently renders: a uniform `SphereGeometry`,
 *  or the close-zoom terrain window's explicit row/column angles. */
type SurfaceGrid =
	| { kind: 'uniform'; segs: number }
	| { kind: 'window'; thetas: Float64Array; phis: Float64Array; key: string };

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

/**
 * Displaced ellipsoid point (km) the mesh draws at `latRad`/`lonRad`: the unit
 * normal scaled by the per-axis semi-axes (a,c,b on local x,y,z — see
 * `applyRadiiToMesh`), grown radially by the displacement. Mirrors the vertex
 * shader exactly, so a corner here is the rendered vertex position.
 */
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
	const cosLat = Math.cos(latRad);
	const nx = cosLat * Math.cos(lonRad);
	const ny = Math.sin(latRad);
	const nz = -cosLat * Math.sin(lonRad);
	return [f * a * nx, f * c * ny, f * b * nz];
}

function ensureSurfacePoint(
	probeId: string,
	landingBodyId: string,
	radiusKm: number,
	latRad: number,
	lonRad: number,
	grid: SurfaceGrid,
	tier: string
): void {
	const key = (grid.kind === 'uniform' ? `u${grid.segs}` : grid.key) + `|${tier}`;
	if (surfacePointPending.has(probeId) || surfacePointKey.get(probeId) === key) return;
	surfacePointPending.add(probeId);
	void (async () => {
		try {
			const global = (await fetchObjectDetail(landingBodyId, false)).global;
			const dispMeta = global?.displacement;
			const { a, b, c } = global?.radii ?? { a: radiusKm, b: radiusKm, c: radiusKm };
			// Grid cell bracketing the probe: theta runs from the +Y pole, phi from 0
			// (body-fixed lng = phi + π). Snap to the cell and keep the fractional
			// position for the in-triangle interpolation.
			let corners: { latRad: number; lonRad: number }[];
			let tx: number;
			let ty: number;
			if (grid.kind === 'uniform') {
				const segs = grid.segs;
				const gy = ((Math.PI / 2 - latRad) * segs) / Math.PI;
				const iy0 = Math.min(Math.max(Math.floor(gy), 0), segs - 1);
				ty = Math.min(Math.max(gy - iy0, 0), 1);
				const gx = ((lonRad - Math.PI) * segs) / (2 * Math.PI);
				const ix0 = Math.floor(gx);
				tx = gx - ix0;
				corners = [
					[iy0, ix0],
					[iy0, ix0 + 1],
					[iy0 + 1, ix0],
					[iy0 + 1, ix0 + 1]
				].map(([iy, ix]) => ({
					latRad: Math.PI / 2 - (Math.min(iy, segs) * Math.PI) / segs,
					lonRad: Math.PI + (ix * 2 * Math.PI) / segs
				}));
			} else {
				const { thetas, phis } = grid;
				const theta = Math.PI / 2 - latRad;
				let phi = (lonRad - Math.PI) % (2 * Math.PI);
				if (phi < 0) phi += 2 * Math.PI;
				const iy0 = cellIndex(thetas, theta);
				const ix0 = cellIndex(phis, phi);
				ty = Math.min(Math.max((theta - thetas[iy0]) / (thetas[iy0 + 1] - thetas[iy0]), 0), 1);
				tx = Math.min(Math.max((phi - phis[ix0]) / (phis[ix0 + 1] - phis[ix0]), 0), 1);
				corners = [
					[iy0, ix0],
					[iy0, ix0 + 1],
					[iy0 + 1, ix0],
					[iy0 + 1, ix0 + 1]
				].map(([iy, ix]) => ({
					latRad: Math.PI / 2 - thetas[iy],
					lonRad: phis[ix] + Math.PI
				}));
			}
			// Displacement (km) the mesh adds at each corner; 0 with no height map.
			let disp = [0, 0, 0, 0];
			if (dispMeta) {
				const offsets = await sampleDisplacementOffsets(
					dispMeta,
					corners,
					kmToScene(radiusKm),
					tier
				);
				if (offsets) disp = Array.from(offsets, sceneToKm);
			}
			const pts = corners.map((corner, k) =>
				displacedPoint(corner.latRad, corner.lonRad, disp[k], radiusKm, a, b, c)
			);
			// Barycentric on the triangle the mesh draws: both grid builders split
			// each quad along the TL–BR diagonal ((a,b,d) + (b,c,d) with b=TL, d=BR).
			const [tl, tr, bl, br] = pts;
			const seat: [number, number, number] = [0, 0, 0];
			for (let axis = 0; axis < 3; axis++) {
				seat[axis] =
					tx >= ty
						? tl[axis] + (tr[axis] - tl[axis]) * tx + (br[axis] - tr[axis]) * ty
						: tl[axis] + (br[axis] - bl[axis]) * tx + (bl[axis] - tl[axis]) * ty;
			}
			surfacePointKm.set(probeId, seat);
			surfacePointKey.set(probeId, key);
		} finally {
			surfacePointPending.delete(probeId);
		}
	})();
}

/**
 * Place a landed probe on its landing body's rendered surface at the record's
 * lat/lng (see {@link surfacePointKm}). Returns null when the landing body isn't
 * loaded or lacks orientation data (caller hides the probe for the frame).
 * Mutates `d.parentId` so the downstream trail geometry and trail-anchor writes
 * follow the new parent.
 */
export function renderLandedProbe(
	d: BodyData,
	probe: Probe,
	landed: LandedRecord,
	jd: number,
	positionMap: Map<string, Vec3>,
	ctx: ContextManager,
	bodyObjects: Map<string, BodyObjects>
): { x: number; y: number; z: number; parentPos: Vec3 } | null {
	const sample = landedPositionAt(landed, jd);
	if (!sample) return null;
	const bodyKey = `naif-${landed.bodyNaifId}`;
	const landingBody = ctx.bodies.bodiesById.get(bodyKey);
	if (!landingBody || !landingBody.orientation) return null;
	const bodyWorldPos = positionMap.get(bodyKey);
	if (!bodyWorldPos) return null;
	const radiusKm = landingBody.data.radiusKm;
	if (!Number.isFinite(radiusKm) || radiusKm <= 0) return null;
	const DEG2RAD = Math.PI / 180;
	const latR = sample.latDeg * DEG2RAD;
	const lngR = sample.lngDeg * DEG2RAD;
	// Seat on the rendered triangle the mesh draws at its current LOD, not the
	// record's altitude over a mean-radius sphere (kilometres off the terrain).
	// Only a probe inside the terrain window's fine region tracks the window
	// (keyed on step level + texture width — fine points sit at absolute step
	// multiples, so recenter rebuilds reuse the seat) and the loaded DEM tier.
	// Outside it the cells are the coarse grid, where the uniform low-tier seat
	// is already right — pinning that key spares every other lander a refetch
	// and heavy decode per window/tier change.
	const bo = bodyObjects.get(bodyKey);
	const tw = bo?.terrainWindow;
	let grid: SurfaceGrid = { kind: 'uniform', segs: bo?.currentSegments ?? 128 };
	let tier = 'low';
	if (tw) {
		const theta = Math.PI / 2 - latR;
		let phi = (lngR - Math.PI) % (2 * Math.PI);
		if (phi < 0) phi += 2 * Math.PI;
		const cosDist =
			Math.sin(theta) * Math.sin(tw.centerTheta) * Math.cos(phi - tw.centerPhi) +
			Math.cos(theta) * Math.cos(tw.centerTheta);
		if (Math.acos(Math.min(1, Math.max(-1, cosDist))) < tw.angRadius) {
			grid = {
				kind: 'window',
				thetas: tw.thetas,
				phis: tw.phis,
				key: `w${tw.stepLevel}x${tw.texWidth}`
			};
			tier = bo?.displacementTier ?? 'low';
		}
	}
	ensureSurfacePoint(d.id, bodyKey, radiusKm, latR, lngR, grid, tier);
	let bx: number;
	let by: number;
	let bz: number;
	const point = surfacePointKm.get(d.id);
	if (point) {
		[bx, by, bz] = point;
	} else {
		// Mean-radius sphere until the cached surface point resolves. Body-fixed
		// XYZ, IAU convention: +X = prime meridian, +Y = north pole, −Z = east.
		const cosLat = Math.cos(latR);
		bx = radiusKm * cosLat * Math.cos(lngR);
		by = radiusKm * Math.sin(latR);
		bz = -radiusKm * cosLat * Math.sin(lngR);
	}
	const quat = bodyQuaternion(landingBody.orientation, jd, landingBody.nutPrec);
	const tmp = new Vector3(bx, by, bz).applyQuaternion(quat);
	// `tmp` is body-relative km in scene-frame; no axis swap needed because
	// `bodyQuaternion` already returns a Three.js-coords rotation.
	d.parentId = bodyKey;
	return {
		x: bodyWorldPos[0] + kmToScene(tmp.x),
		y: bodyWorldPos[1] + kmToScene(tmp.y),
		z: bodyWorldPos[2] + kmToScene(tmp.z),
		parentPos: bodyWorldPos
	};
}
