import { ObjectType, effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import { kmToScene } from '$lib/math/units';
import type { PerspectiveCamera, Quaternion } from 'three';
import { Vector3 } from 'three';
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

/** Clearance between the near-plane rectangle and the terrain under a landed
 *  probe's camera. Covers the mesh's float32 vertex rounding (~0.4 m worst on
 *  Mars-sized bodies) — the CPU terrain samples are exact doubles. */
export const LANDED_KEEP_AWAY_KM = 0.0005;

/** How to evaluate the rendered terrain under the camera when the focused
 *  probe is landed on `body`. */
export interface LandedClampContext {
	/** Scene-frame → body-fixed rotation (inverse of the body's `bodyQuaternion`). */
	invQuat: Quaternion;
	/** Rendered-surface distance (km) from the body centre along a body-fixed
	 *  unit direction; null while its data loads (fallback: shell at the probe). */
	radialKm: (dir: [number, number, number]) => number | null;
}

const _dirBF = new Vector3();
const _corner = new Vector3();

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
 * For a `landed` probe the floor is the rendered terrain itself, and the
 * guarded shape is the near-plane rectangle, not just the eye: the rectangle
 * extends ±tan(fov/2)·near (×aspect) around the view axis, and terrain crossing
 * it is near-clipped into a see-through hole even with the eye above ground.
 * Each of the eye + four corners is checked against the terrain radial along
 * its own direction (+ keep-away) and the camera is lifted radially by the
 * worst deficit. Until the terrain data resolves, a shell at the probe's own
 * radial distance stands in.
 */
export function clampCameraOutsideBody(
	camera: PerspectiveCamera,
	body: PositionedBody,
	focusTruePos: Vec3,
	landed?: LandedClampContext
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

	let dx = camera.position.x - cx;
	let dy = camera.position.y - cy;
	let dz = camera.position.z - cz;
	const dist = Math.hypot(dx, dy, dz);

	if (landed) {
		if (dist < 1e-9) {
			// Camera exactly at center: pick an arbitrary radial to escape along.
			camera.position.set(cx, cy + focusDist + kmToScene(LANDED_KEEP_AWAY_KM), cz);
			return;
		}
		const hh = Math.tan((camera.fov * Math.PI) / 360) * camera.near;
		const hw = hh * camera.aspect;
		let lift = 0;
		for (const [ox, oy, oz] of [
			[0, 0, 0],
			[-hw, -hh, -camera.near],
			[hw, -hh, -camera.near],
			[-hw, hh, -camera.near],
			[hw, hh, -camera.near]
		]) {
			_corner.set(ox, oy, oz).applyQuaternion(camera.quaternion);
			const px = dx + _corner.x;
			const py = dy + _corner.y;
			const pz = dz + _corner.z;
			const r = Math.hypot(px, py, pz);
			if (r < 1e-12) continue;
			_dirBF.set(px / r, py / r, pz / r).applyQuaternion(landed.invQuat);
			const sKm = landed.radialKm([_dirBF.x, _dirBF.y, _dirBF.z]);
			const wall = (sKm !== null ? kmToScene(sKm) : focusDist) + kmToScene(LANDED_KEEP_AWAY_KM);
			if (wall - r > lift) lift = wall - r;
		}
		if (lift <= 0) return;
		// Radial lift raises every sample point by ~the same amount (they sit
		// metres apart on a planet-sized radius), so one pass settles it.
		const k = lift / dist;
		camera.position.set(
			camera.position.x + dx * k,
			camera.position.y + dy * k,
			camera.position.z + dz * k
		);
		return;
	}

	const surface = Math.min(kmToScene(radiusKm + surfaceClearanceKm(body)), focusDist);
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
