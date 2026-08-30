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

/** How to evaluate the rendered surface under the camera: the displaced DEM
 *  for a sphere-meshed body, a mesh cast for a mounted shape model. */
export interface SurfaceClampContext {
	/** Scene-frame → body-fixed rotation (inverse of the body's `bodyQuaternion`). */
	invQuat: Quaternion;
	/** Rendered-surface distance (km) from the body centre along a body-fixed
	 *  unit direction; null while its data loads (fallback: the sphere). */
	radialKm: (dir: [number, number, number]) => number | null;
	/** Seated view (landed probe, surface feature): guard the whole near-plane
	 *  rectangle and floor it on the terrain, instead of the eye alone. */
	seated?: boolean;
	/** Radius (km) of a sphere the surface certainly fits inside. Outside it the
	 *  clamp returns without sampling — a shape model reaches past the body's
	 *  quoted radius, so that alone can't gate the sampling. Only a gate: where
	 *  the sampler finds nothing the wall stays at the quoted radius. */
	outerRadiusKm?: number;
	/** Where the sampler measures its radii from, offset from the body centre
	 *  in scene units. A shape model is drawn recentred on its bounding box,
	 *  which sits kilometres off the model's own origin on a lopsided body —
	 *  measuring the camera's radial from the wrong point walls it inside the
	 *  mesh. Absent (the DEM's case) means the body centre. */
	centerOffsetScene?: Vec3;
}

const _dirBF = new Vector3();
const _corner = new Vector3();

/** Surface clearance in km for a body. Spacecraft/debris span ~0.3 m to ~100 m;
 *  a fixed clearance would block close approach to tiny craft, so fall back to a
 *  fraction of the radius to keep max zoom-in proportional to real size. */
function surfaceClearanceKm(body: PositionedBody): number {
	return SURFACE_CLEARANCE_KM[body.data.objectType] ?? effectiveRadiusKm(body.data) * 0.25;
}

/** Closest the orbit controls may bring the camera to `body`'s centre.
 *  `minRadiusKm` (a shape model's inscribed radius) replaces the quoted radius:
 *  the fence is a sphere, so an elongated model would otherwise wall the camera
 *  off far from its narrow sides — {@link clampCameraOutsideBody} holds the
 *  real surface there. */
export function minCameraDistance(body: PositionedBody, minRadiusKm?: number): number {
	return kmToScene((minRadiusKm ?? effectiveRadiusKm(body.data)) + surfaceClearanceKm(body));
}

/**
 * Pushes the camera off `body`'s surface (+ clearance) if it penetrated —
 * stops tunnelling into the focused object's parent (e.g. Earth while
 * focused on the ISS). Mutates `camera.position`; no-op for zero-radius bodies.
 *
 * For an orbiter, the wall never exceeds the focused object's own distance,
 * so a very-low orbiter's clearance doesn't fence the camera off from it.
 *
 * Without a `surface` sampler the wall is a sphere at the body's radius; with
 * one it follows the rendered surface along the camera's own radial, which is
 * what a shape model needs — its mesh reaches well past that sphere.
 *
 * A `seated` view (landed probe, surface feature) floors on the surface with
 * no orbiter cap, and guards the near-plane rectangle rather than the eye —
 * terrain crossing it near-clips into a see-through hole. Each corner is
 * checked against its own radial and the camera lifted by the worst deficit.
 */
export function clampCameraOutsideBody(
	camera: PerspectiveCamera,
	body: PositionedBody,
	focusTruePos: Vec3,
	surface?: SurfaceClampContext
): void {
	const radiusKm = body.data.radiusKm;
	if (!Number.isFinite(radiusKm) || radiusKm <= 0) return;

	// Body center relative to the focus origin (camera.position shares this frame).
	const bx = body.position[0] - focusTruePos[0];
	const by = body.position[1] - focusTruePos[1];
	const bz = body.position[2] - focusTruePos[2];
	// Focus origin (0,0,0) is the focused object, so this is its distance to the
	// parent center — i.e. the ground level right under a landed probe.
	const focusDist = Math.hypot(bx, by, bz);

	// Radii are measured — and the camera pushed — from where the surface is
	// centred, which a recentred shape model puts off the body centre. The
	// offset carries no rotation: the mount only scales.
	const off = surface?.centerOffsetScene;
	const cx = bx + (off ? off[0] : 0);
	const cy = by + (off ? off[1] : 0);
	const cz = bz + (off ? off[2] : 0);

	let dx = camera.position.x - cx;
	let dy = camera.position.y - cy;
	let dz = camera.position.z - cz;
	const dist = Math.hypot(dx, dy, dz);

	if (surface?.seated) {
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
			_dirBF.set(px / r, py / r, pz / r).applyQuaternion(surface.invQuat);
			const sKm = surface.radialKm([_dirBF.x, _dirBF.y, _dirBF.z]);
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

	const clearanceKm = surfaceClearanceKm(body);
	// The bounding sphere gates the sampling, but never becomes the wall: for a
	// lumpy model it sits well outside the surface, and falling back to it would
	// fling a close-up camera out by most of a radius.
	if (dist >= kmToScene((surface?.outerRadiusKm ?? radiusKm) + clearanceKm)) return;

	let wallKm = radiusKm;
	if (surface && dist > 1e-9) {
		_dirBF.set(dx / dist, dy / dist, dz / dist).applyQuaternion(surface.invQuat);
		wallKm = surface.radialKm([_dirBF.x, _dirBF.y, _dirBF.z]) ?? radiusKm;
	}
	// The cap keeps the focused object itself reachable; clamping against the
	// focused body (focusDist 0) has nothing to stay clear of.
	const wallScene = kmToScene(wallKm + clearanceKm);
	const wall = focusDist > 0 ? Math.min(wallScene, focusDist) : wallScene;
	if (dist >= wall) return;

	if (dist < 1e-9) {
		// Camera exactly at center: pick an arbitrary radial to escape along.
		dx = 0;
		dy = wall;
		dz = 0;
	} else {
		// The push is radial, so it leaves the sampled direction — and the wall
		// on it — unchanged; one pass settles.
		const k = wall / dist;
		dx *= k;
		dy *= k;
		dz *= k;
	}
	camera.position.set(cx + dx, cy + dy, cz + dz);
}
