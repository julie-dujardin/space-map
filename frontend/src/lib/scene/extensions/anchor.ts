/**
 * A place on the map that keeps up with it. Everything a host adds — markers,
 * lines, later a camera pose — is placed by one of these, so it follows its
 * body as the clock runs and survives the origin moving under it.
 *
 * Offsets are kilometres on ecliptic J2000 axes, the frame the export's
 * positions are published in. Latitude and longitude are body-fixed and turn
 * with the body, as its surface features do.
 */

import { bodyQuaternion } from '$lib/math/orientation';
import { kmToScene } from '$lib/math/units';
import { eclipticToScene } from '$lib/math/travel/state';
import { effectiveRadiusKm } from '$lib/types/objects';
import type { Vec3 } from '$lib/scene/animation/math';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

/** Kilometres on ecliptic J2000 axes, x toward the equinox and z toward the
 *  ecliptic north pole. */
export type OffsetKm = readonly [number, number, number];

/** Fixed in the body's inertial frame: it travels with the body but does not
 *  turn with it. The body's centre when the offset is left out. */
export interface InertialAnchor {
	body: string;
	offsetKm?: OffsetKm | ((jd: number) => OffsetKm);
}

/** A place on (or above) the body's surface, turning with it. */
export interface SurfaceAnchor {
	body: string;
	latitude: number;
	longitude: number;
	/** Height above the body's mean radius; on the surface when left out. */
	altitudeKm?: number;
}

export type Anchor = InertialAnchor | SurfaceAnchor;

const RAD = Math.PI / 180;

function isSurface(anchor: Anchor): anchor is SurfaceAnchor {
	return 'latitude' in anchor;
}

/** Body-fixed unit vector for lat/lon in the scene's axes, before the body's
 *  own rotation: latitude 0, longitude 0 on +X, longitude increasing east.
 *  Matches the texture convention {@link bodyQuaternion} establishes. */
function surfaceDirection(latitude: number, longitude: number): Vec3 {
	const lat = latitude * RAD;
	const lon = longitude * RAD;
	return [Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon)];
}

/** World position of `anchor` in scene units, or null while its body is not
 *  loaded — which is normal: an embed can mark a place the reader has not
 *  travelled to yet. */
export function resolveAnchor(anchor: Anchor, ctx: ContextManager, jd: number): Vec3 | null {
	const body = ctx.getBody(anchor.body);
	if (!body) return null;
	const [cx, cy, cz] = body.position;

	if (isSurface(anchor)) {
		const distance = kmToScene(effectiveRadiusKm(body.data) + (anchor.altitudeKm ?? 0));
		const [dx, dy, dz] = surfaceDirection(anchor.latitude, anchor.longitude);
		// Without orientation metadata the body has no measured spin, so the
		// place is put on the unrotated sphere rather than nowhere.
		const q = body.orientation ? bodyQuaternion(body.orientation, jd, body.nutPrec) : null;
		if (!q) return [cx + dx * distance, cy + dy * distance, cz + dz * distance];
		// Quaternion rotation of (dx, dy, dz), written out to stay off the heap
		// in the per-frame path.
		const tx = 2 * (q.y * dz - q.z * dy);
		const ty = 2 * (q.z * dx - q.x * dz);
		const tz = 2 * (q.x * dy - q.y * dx);
		const rx = dx + q.w * tx + (q.y * tz - q.z * ty);
		const ry = dy + q.w * ty + (q.z * tx - q.x * tz);
		const rz = dz + q.w * tz + (q.x * ty - q.y * tx);
		return [cx + rx * distance, cy + ry * distance, cz + rz * distance];
	}

	const offset = typeof anchor.offsetKm === 'function' ? anchor.offsetKm(jd) : anchor.offsetKm;
	if (!offset) return [cx, cy, cz];
	const [ox, oy, oz] = eclipticToScene(offset as Vec3);
	return [cx + ox, cy + oy, cz + oz];
}

/** Unit vector from the body's centre toward the anchor, for the occlusion
 *  test; null when the anchor sits at the centre. */
export function anchorNormal(anchor: Anchor, world: Vec3, ctx: ContextManager): Vec3 | null {
	const body = ctx.getBody(anchor.body);
	if (!body) return null;
	const dx = world[0] - body.position[0];
	const dy = world[1] - body.position[1];
	const dz = world[2] - body.position[2];
	const length = Math.hypot(dx, dy, dz);
	if (length === 0) return null;
	return [dx / length, dy / length, dz / length];
}
