import { Vector3 } from 'three';
import type { BodyData } from '$lib/types/objects';
import type { LandedRecord, Probe } from '$lib/fetch/position/probes/parse';
import { landedPositionAt } from '$lib/fetch/position/probes/propagate';
import { kmToScene, sceneToKm } from '$lib/math/units';
import { bodyQuaternion } from '$lib/math/orientation';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { sampleDisplacementOffsets } from '$lib/scene/objects/surface/displacement';
import {
	displacedPoint,
	gridCell,
	triangleNormalKm,
	trianglePointKm,
	type SurfaceGrid
} from './rendered-surface';
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
/** Unit facet normal (body-fixed) matching the seat — the probe's up on the slope. */
const surfaceNormal = new Map<string, [number, number, number]>();
const surfacePointKey = new Map<string, string>();
const surfacePointPending = new Set<string>();

/** Bumped whenever any probe's seat resolves. The renderer watches it to run a
 *  position pass while paused — seats resolve asynchronously, and without a jd
 *  change nothing else would apply the new seat. */
let seatEpoch = 0;

export function landedSeatEpoch(): number {
	return seatEpoch;
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
			const { corners, tx, ty } = gridCell(grid, latRad, lonRad);
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
			const seat = trianglePointKm(pts, tx, ty);
			surfacePointKm.set(probeId, seat);
			surfaceNormal.set(probeId, triangleNormalKm(pts, tx, ty));
			surfacePointKey.set(probeId, key);
			seatEpoch++;
		} finally {
			surfacePointPending.delete(probeId);
		}
	})();
}

const _upScene = new Vector3();

/**
 * Place a landed probe on its landing body's rendered surface at the record's
 * lat/lng (see {@link surfacePointKm}). Returns null when the landing body isn't
 * loaded or lacks orientation data (caller hides the probe for the frame).
 * `up` is the seat facet's normal in scene frame (the probe stands on the
 * slope, not the radial); null until the seat resolves. Scratch-backed —
 * consume within the frame. Mutates `d.parentId` so the downstream trail
 * geometry and trail-anchor writes follow the new parent.
 */
export function renderLandedProbe(
	d: BodyData,
	probe: Probe,
	landed: LandedRecord,
	jd: number,
	positionMap: Map<string, Vec3>,
	ctx: ContextManager,
	bodyObjects: Map<string, BodyObjects>
): { x: number; y: number; z: number; parentPos: Vec3; up: Vector3 | null } | null {
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
	const normal = point ? surfaceNormal.get(d.id) : undefined;
	const up = normal ? _upScene.set(normal[0], normal[1], normal[2]).applyQuaternion(quat) : null;
	// `tmp` is body-relative km in scene-frame; no axis swap needed because
	// `bodyQuaternion` already returns a Three.js-coords rotation.
	d.parentId = bodyKey;
	return {
		x: bodyWorldPos[0] + kmToScene(tmp.x),
		y: bodyWorldPos[1] + kmToScene(tmp.y),
		z: bodyWorldPos[2] + kmToScene(tmp.z),
		parentPos: bodyWorldPos,
		up
	};
}
