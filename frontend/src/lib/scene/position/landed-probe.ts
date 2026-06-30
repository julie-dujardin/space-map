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
 * Body-fixed surface seat (km, pre-orientation) per landed probe, with the
 * sphere-LOD segment count it was computed for. The mesh renders as flat
 * triangles between `SphereGeometry` grid vertices (≤128 segs → ~166 km facets
 * on Mars), and each facet's chord dips up to ~1 km below the smooth ellipsoid,
 * so seating on the analytic surface left the probe floating. We instead sample
 * the four grid vertices bracketing the probe and bilinearly blend — the exact
 * point on the rendered triangle. Recomputed when the LOD segment count changes;
 * the record's altitude is unused (coarse height maps make it float/sink).
 * Absent until first resolved (probe rests on the mean-radius sphere meanwhile).
 */
const surfacePointKm = new Map<string, [number, number, number]>();
const surfacePointSegs = new Map<string, number>();
const surfacePointPending = new Set<string>();

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
	segs: number
): void {
	if (surfacePointPending.has(probeId) || surfacePointSegs.get(probeId) === segs) return;
	surfacePointPending.add(probeId);
	void (async () => {
		try {
			const global = (await fetchObjectDetail(landingBodyId, false)).global;
			const dispMeta = global?.displacement;
			const { a, b, c } = global?.radii ?? { a: radiusKm, b: radiusKm, c: radiusKm };
			// SphereGeometry grid cell bracketing the probe: theta runs from the +Y
			// pole, phi from 0 (body-fixed lng = phi + π). Snap to the cell and keep
			// the fractional position for the bilinear blend.
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
			// Displacement (km) the mesh adds at each corner; 0 with no height map.
			let disp = [0, 0, 0, 0];
			if (dispMeta) {
				const offsets = await sampleDisplacementOffsets(dispMeta, corners, kmToScene(radiusKm));
				if (offsets) disp = Array.from(offsets, sceneToKm);
			}
			const pts = corners.map((corner, k) =>
				displacedPoint(corner.latRad, corner.lonRad, disp[k], radiusKm, a, b, c)
			);
			const seat: [number, number, number] = [0, 0, 0];
			for (let axis = 0; axis < 3; axis++) {
				const top = pts[0][axis] * (1 - tx) + pts[1][axis] * tx;
				const bot = pts[2][axis] * (1 - tx) + pts[3][axis] * tx;
				seat[axis] = top * (1 - ty) + bot * ty;
			}
			surfacePointKm.set(probeId, seat);
			surfacePointSegs.set(probeId, segs);
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
	const segs = bodyObjects.get(bodyKey)?.currentSegments ?? 128;
	ensureSurfacePoint(d.id, bodyKey, radiusKm, latR, lngR, segs);
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
