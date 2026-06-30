import { Vector3 } from 'three';
import type { BodyData } from '$lib/types/objects';
import type { LandedRecord, Probe } from '$lib/fetch/position/probes/parse';
import { landedPositionAt } from '$lib/fetch/position/probes/propagate';
import { kmToScene, sceneToKm } from '$lib/math/units';
import { bodyQuaternion } from '$lib/math/orientation';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { sampleDisplacementOffsets } from '$lib/scene/objects/surface/displacement';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { Vec3 } from '$lib/scene/animation/math';

/**
 * Body-fixed surface point (km, pre-orientation) per landed probe, keyed by id.
 * The body renders as a triaxial ellipsoid (axes a,c,b on local x,y,z — see
 * `applyRadiiToMesh`) plus displacement, so a mean-radius sphere leaves the probe
 * kilometres off; we reconstruct the exact point the mesh shows. The record's
 * altitude is ignored — coarse height maps make it float/sink. Fixed per probe,
 * so sampled once; absent until then (probe rests on the mean-radius sphere).
 */
const surfacePointKm = new Map<string, [number, number, number]>();
const surfacePointPending = new Set<string>();

function ensureSurfacePoint(
	probeId: string,
	landingBodyId: string,
	radiusKm: number,
	latRad: number,
	lonRad: number
): void {
	if (surfacePointKm.has(probeId) || surfacePointPending.has(probeId)) return;
	surfacePointPending.add(probeId);
	void (async () => {
		try {
			const global = (await fetchObjectDetail(landingBodyId, false)).global;
			const dispMeta = global?.displacement;
			// Displacement (km) the mesh adds along the base-sphere normal at this
			// lat/lng; 0 when the body has no height map.
			let dispKm = 0;
			if (dispMeta) {
				const offsets = await sampleDisplacementOffsets(
					dispMeta,
					[{ latRad, lonRad }],
					kmToScene(radiusKm)
				);
				if (offsets) dispKm = sceneToKm(offsets[0]);
			}
			// Mesh scales the displaced unit normal by the per-axis semi-axes; mirror
			// that exactly. Falls back to a sphere of `radiusKm` when radii are absent.
			const { a, b, c } = global?.radii ?? { a: radiusKm, b: radiusKm, c: radiusKm };
			const f = (radiusKm + dispKm) / radiusKm;
			const cosLat = Math.cos(latRad);
			const nx = cosLat * Math.cos(lonRad);
			const ny = Math.sin(latRad);
			const nz = -cosLat * Math.sin(lonRad);
			surfacePointKm.set(probeId, [f * a * nx, f * c * ny, f * b * nz]);
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
	ctx: ContextManager
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
	// Snap to the displaced ellipsoid the mesh draws, not the record's altitude
	// over a mean-radius sphere (kilometres off the visible terrain).
	ensureSurfacePoint(d.id, bodyKey, radiusKm, latR, lngR);
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
