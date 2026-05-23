import { Vector3 } from 'three';
import type { BodyData } from '$lib/types/objects';
import type { LandedRecord, Probe } from '$lib/fetch/position/probes/parse';
import { landedPositionAt } from '$lib/fetch/position/probes/propagate';
import { kmToScene } from '$lib/math/units';
import { bodyQuaternion } from '$lib/math/orientation';
import type { ContextManager } from '$lib/scene/context-manager.svelte';
import type { Vec3 } from '$lib/scene/animation/math';

/**
 * Place a landed probe at its body-surface lat/lng/alt in world coords.
 * Returns null when the landing body isn't loaded or lacks orientation data
 * (caller hides the probe for the frame). Mutates `d.parentId` so the
 * downstream orbit-line/trail-anchor writes follow the new parent.
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
	const landingBody = ctx.bodiesById.get(bodyKey);
	if (!landingBody || !landingBody.orientation) return null;
	const bodyWorldPos = positionMap.get(bodyKey);
	if (!bodyWorldPos) return null;
	const radiusKm = landingBody.data.radiusKm;
	if (!Number.isFinite(radiusKm) || radiusKm <= 0) return null;
	const DEG2RAD = Math.PI / 180;
	const latR = sample.latDeg * DEG2RAD;
	const lngR = sample.lngDeg * DEG2RAD;
	// Body-fixed XYZ in km, IAU convention: +X = prime meridian, +Y = north
	// pole, −Z = east. Sphere approximation: geodetic-vs-spherical error is
	// well below the rendered probe's pixel size for typical flattenings.
	const r = radiusKm + sample.altM / 1000;
	const cosLat = Math.cos(latR);
	const bx = r * cosLat * Math.cos(lngR);
	const by = r * Math.sin(latR);
	const bz = -r * cosLat * Math.sin(lngR);
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
