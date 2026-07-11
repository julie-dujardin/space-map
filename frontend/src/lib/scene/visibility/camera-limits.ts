import { ObjectType, effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import type { PerspectiveCamera } from 'three';
import type { Vec3 } from '$lib/scene/animation/math';

/** Default surface clearance in km, by object type. */
const SURFACE_CLEARANCE_KM: Partial<Record<ObjectType, number>> = {
	[ObjectType.STAR]: 1000,
	[ObjectType.PLANET]: 100,
	[ObjectType.DWARF_PLANET]: 10,
	[ObjectType.ASTEROID]: 0.1,
	[ObjectType.ASTEROID_INNER]: 0.1,
	[ObjectType.ASTEROID_MAIN_BELT]: 0.1,
	[ObjectType.ASTEROID_CENTAUR]: 1,
	[ObjectType.ASTEROID_TROJAN]: 1,
	[ObjectType.ASTEROID_TNO]: 1,
	[ObjectType.COMET]: 1,
	[ObjectType.MOON]: 1
};

/** Camera floor above a landed probe's own ground spot — lets you inspect the
 *  probe up close without the camera clipping through the terrain under it. */
export const LANDED_KEEP_AWAY_KM = 0.001;

/** Surface clearance in km for a body. Spacecraft/debris span ~0.3 m to ~100 m;
 *  a fixed clearance would block close approach to tiny craft, so fall back to a
 *  fraction of the radius to keep max zoom-in proportional to real size. */
function surfaceClearanceKm(body: PositionedBody): number {
	return SURFACE_CLEARANCE_KM[body.data.objectType] ?? effectiveRadiusKm(body.data) * 0.25;
}

export function minCameraDistance(body: PositionedBody): number {
	return kmToScene(effectiveRadiusKm(body.data) + surfaceClearanceKm(body));
}

/**
 * Push the camera out to `body`'s surface (+ clearance) if it has penetrated the
 * body — used to stop the camera tunnelling into the focused object's parent
 * (e.g. Earth while focused on the ISS). `camera.position` is in focus-relative
 * render space, so `body`'s center is offset by the focus origin. No-op for
 * bodies with no real radius (barycenters). Mutates `camera.position`.
 *
 * For an orbiter the wall is never placed farther from the parent's center than
 * the focused object itself: a very-low orbiter can ride below the clearance
 * line, so a fixed radius+clearance wall would fence the camera off from the very
 * thing it's focused on. Capping at the focus's own radial distance keeps it
 * reachable while still blocking the sub-surface volume.
 *
 * A `landed` probe instead gets a thin keep-away shell 1 m above its own ground
 * spot, so you can inspect it up close without the camera clipping the terrain.
 */
export function clampCameraOutsideBody(
	camera: PerspectiveCamera,
	body: PositionedBody,
	focusTruePos: Vec3,
	landed = false
): void {
	const radiusKm = body.data.radiusKm;
	if (!Number.isFinite(radiusKm) || radiusKm <= 0) return;

	// Body center relative to the focus origin (camera.position shares this frame).
	const cx = body.position[0] - focusTruePos[0];
	const cy = body.position[1] - focusTruePos[1];
	const cz = body.position[2] - focusTruePos[2];
	// Focus origin (0,0,0) is the focused object, so this is its distance to the
	// parent center — i.e. the ground level right under a landed probe.
	const focusDist = Math.hypot(cx, cy, cz);
	const surface = landed
		? focusDist + kmToScene(LANDED_KEEP_AWAY_KM)
		: Math.min(kmToScene(radiusKm + surfaceClearanceKm(body)), focusDist);

	let dx = camera.position.x - cx;
	let dy = camera.position.y - cy;
	let dz = camera.position.z - cz;
	const dist = Math.hypot(dx, dy, dz);
	if (dist >= surface) return;

	if (dist < 1e-9) {
		// Camera exactly at center: pick an arbitrary radial to escape along.
		dx = 0;
		dy = surface;
		dz = 0;
	} else {
		const k = surface / dist;
		dx *= k;
		dy *= k;
		dz *= k;
	}
	camera.position.set(cx + dx, cy + dy, cz + dz);
}
