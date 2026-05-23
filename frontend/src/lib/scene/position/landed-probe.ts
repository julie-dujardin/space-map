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
 *
 * Steps:
 *   1. Stair-step lookup into the landed record at `jd` → (lat, lng, alt_m).
 *   2. Find the landing body in `bodiesById` (e.g. naif-499 for Mars).
 *   3. Compute body-fixed XYZ from (lat, lng, alt) — Three.js convention:
 *      local +X = prime meridian, +Y = north pole, −Z = east.
 *   4. Rotate by the body's IAU quaternion (pole + spin at `jd`, with
 *      nutation/precession sums if present) to land in scene-frame coords.
 *   5. Convert to scene units and add to the body's world position.
 *
 * Returns null when the landing body isn't loaded yet (e.g. Titan chebyshev
 * chunk still streaming) or lacks orientation data — caller marks the
 * probe out-of-range for one frame and tries again next tick.
 *
 * Side effect: mutates `d.parentId` to the landing body's NAIF key so the
 * orbit-line / trail-anchor writes downstream in `computePosition` follow
 * the new parent in the same frame.
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
	// Spherical body-fixed XYZ in km (sphere approximation — for typical
	// planet flattenings the geodetic-vs-spherical difference is well below
	// the rendered point's pixel size). Convention matches the IAU body-
	// fixed frame the writer's lat/lng/alt were sampled in:
	//   local +X → prime meridian on equator (lat=0, lon=0)
	//   local +Y → north pole (lat=+90)
	//   local −Z → east (lon=+90)
	const r = radiusKm + sample.altM / 1000;
	const cosLat = Math.cos(latR);
	const bx = r * cosLat * Math.cos(lngR);
	const by = r * Math.sin(latR);
	const bz = -r * cosLat * Math.sin(lngR);
	const quat = bodyQuaternion(landingBody.orientation, jd, landingBody.nutPrec);
	const tmp = new Vector3(bx, by, bz).applyQuaternion(quat);
	// `tmp` is body-relative scene-frame km. Convert to scene units and
	// add to the landing body's world position. The original ECLIPJ2000-→-
	// scene axis swap in `kmToScene` does NOT apply here because
	// `bodyQuaternion` already returns a Three.js-coords rotation.
	d.parentId = bodyKey;
	return {
		x: bodyWorldPos[0] + kmToScene(tmp.x),
		y: bodyWorldPos[1] + kmToScene(tmp.y),
		z: bodyWorldPos[2] + kmToScene(tmp.z),
		parentPos: bodyWorldPos
	};
}
