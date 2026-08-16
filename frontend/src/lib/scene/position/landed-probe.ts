import { Vector3 } from 'three';
import type { BodyData } from '$lib/types/objects';
import type { LandedRecord, Probe } from '$lib/fetch/position/probes/parse';
import { landedOpenEnded, landedPositionAt } from '$lib/fetch/position/probes/propagate';
import { kmToScene } from '$lib/math/units';
import { bodyQuaternion } from '$lib/math/orientation';
import { renderedSeatAt } from './rendered-surface';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { BodyObjects } from '$lib/scene/types';
import type { Vec3 } from '$lib/scene/animation/math';

/** Last resolved seat per probe, held across frames where surface data is
 *  still loading, so the probe doesn't pop onto the mean-radius sphere. */
const lastSeat = new Map<
	string,
	{ pointKm: [number, number, number]; normal: [number, number, number] }
>();

const _upScene = new Vector3();

/**
 * Seats a landed probe on the rendered surface via {@link renderedSeatAt} —
 * the same sampler the camera's terrain floor uses, so they never disagree.
 * The record's altitude is ignored (coarse height maps make it float/sink).
 *
 * Null when the body isn't loaded or lacks orientation data. `up` is the seat
 * normal in scene frame, null until surface data resolves. Scratch-backed —
 * consume within the frame. Mutates `d.parentId` so trail geometry follows.
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
	const sample = landedPositionAt(landed, jd, landedOpenEnded(probe));
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
	const seat = renderedSeatAt(bodyObjects.get(bodyKey), bodyKey, radiusKm, latR, lngR);
	if (seat) lastSeat.set(d.id, seat);
	const eff = seat ?? lastSeat.get(d.id);
	let bx: number;
	let by: number;
	let bz: number;
	if (eff) {
		[bx, by, bz] = eff.pointKm;
	} else {
		// Mean-radius sphere until the surface data resolves. Body-fixed XYZ,
		// IAU convention: +X = prime meridian, +Y = north pole, −Z = east.
		const cosLat = Math.cos(latR);
		bx = radiusKm * cosLat * Math.cos(lngR);
		by = radiusKm * Math.sin(latR);
		bz = -radiusKm * cosLat * Math.sin(lngR);
	}
	const quat = bodyQuaternion(landingBody.orientation, jd, landingBody.nutPrec);
	const tmp = new Vector3(bx, by, bz).applyQuaternion(quat);
	const up = eff
		? _upScene.set(eff.normal[0], eff.normal[1], eff.normal[2]).applyQuaternion(quat)
		: null;
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
