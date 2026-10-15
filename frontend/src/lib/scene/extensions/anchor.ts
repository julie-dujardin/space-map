/**
 * A place on the map that keeps up with it. Everything a host adds — markers,
 * lines, later a camera pose — is placed by one of these, so it follows its
 * body as the clock runs and survives the origin moving under it.
 *
 * Offsets are kilometres on ecliptic J2000 axes, the frame the export's
 * positions are published in. Latitude and longitude are body-fixed and turn
 * with the body, as its surface features do.
 */

import type { Quaternion } from 'three';
import { bodyQuaternion } from '$lib/math/orientation';
import { kmToScene } from '$lib/math/units';
import { eclipticToScene } from '$lib/math/travel/state';
import { effectiveRadiusKm, type PositionedBody } from '$lib/types/objects';
import type { Vec3 } from '$lib/scene/animation/math';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

/** Kilometres on ecliptic J2000 axes, x toward the equinox and z toward the
 *  ecliptic north pole. */
export type OffsetKm = readonly [number, number, number];

/** Fixed in the body's inertial frame: it travels with the body but does not
 *  turn with it. The body's centre when the offset is left out. An offset read
 *  from a function is a trajectory — see {@link samples}, {@link elements} and
 *  {@link tle} — and a date it says nothing about returns null, which leaves
 *  whatever the anchor carries undrawn. */
export interface InertialAnchor {
	body: string;
	offsetKm?: OffsetKm | ((jd: number) => OffsetKm | null);
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

/** Semi-axes (km) of a drawn ellipsoid. `a` and `b` are equatorial, along
 *  body-fixed x and z; `c` is polar, along y. */
export type Radii = NonNullable<PositionedBody['drawnRadii']>;

/** Body-fixed unit vector for lat/lon in the scene's axes, before the body's
 *  own rotation: latitude 0, longitude 0 on +X, longitude increasing east.
 *  Matches the texture convention {@link bodyQuaternion} establishes. With
 *  `radii` it points at the place on the drawn ellipsoid instead. */
export function surfaceDirection(latitude: number, longitude: number, radii?: Radii): Vec3 {
	const lat = latitude * RAD;
	const lon = longitude * RAD;
	const out: Vec3 = [Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon)];
	if (radii) onEllipsoid(radii, out, 0, out, 0);
	return out;
}

/** Move the unit direction at `from[at]` to the drawn place with the same
 *  latitude and longitude, into `out[to]`. The mesh and its texture put a
 *  latitude at that parametric angle of the ellipsoid, so on an oblate body
 *  the place is nearer the equator than the direction. */
function onEllipsoid(
	radii: Radii,
	from: ArrayLike<number>,
	at: number,
	out: Float64Array | number[],
	to: number
): void {
	const x = from[at] * radii.a;
	const y = from[at + 1] * radii.c;
	const z = from[at + 2] * radii.b;
	const n = Math.hypot(x, y, z);
	out[to] = x / n;
	out[to + 1] = y / n;
	out[to + 2] = z / n;
}

/** A set of body-fixed unit directions moved onto the drawn ellipsoid, kept
 *  until the directions or the radii change. */
export class GroundDirections {
	private source: Float64Array | null = null;
	private radii: Radii | undefined;
	private out = new Float64Array(0);

	of(dirs: Float64Array, radii: Radii | undefined): Float64Array {
		if (!radii) return dirs;
		if (dirs !== this.source || radii !== this.radii) {
			if (this.out.length !== dirs.length) this.out = new Float64Array(dirs.length);
			for (let i = 0; i < dirs.length; i += 3) onEllipsoid(radii, dirs, i, this.out, i);
			this.source = dirs;
			this.radii = radii;
		}
		return this.out;
	}
}

/** Rotate (x, y, z) by `q` into `out` at index `at`. Written out and given an
 *  output buffer to stay off the heap: a surface shape turns a few thousand of
 *  these every frame. */
export function rotateByQuaternion(
	q: Quaternion,
	x: number,
	y: number,
	z: number,
	out: Float64Array | Float32Array | number[],
	at: number
): void {
	const tx = 2 * (q.y * z - q.z * y);
	const ty = 2 * (q.z * x - q.x * z);
	const tz = 2 * (q.x * y - q.y * x);
	out[at] = x + q.w * tx + (q.y * tz - q.z * ty);
	out[at + 1] = y + q.w * ty + (q.z * tx - q.x * tz);
	out[at + 2] = z + q.w * tz + (q.x * ty - q.y * tx);
}

/** Where `body`'s centre is at `jd`, in scene units, or null while it is
 *  nowhere. */
export function bodyCentre(body: PositionedBody, ctx: ContextManager, jd: number): Vec3 | null {
	return ctx.place(body, jd);
}

/** What an anchor reads of the body it is on. */
export type AnchorBody = Pick<PositionedBody, 'orientation' | 'nutPrec' | 'drawnRadii'> & {
	data: Parameters<typeof effectiveRadiusKm>[0];
};

/** World position of `anchor` in scene units, on a body whose centre is at
 *  `centre`. Null when a moving offset is nowhere at this date. */
export function placeAnchor(
	anchor: Anchor,
	body: AnchorBody,
	centre: Vec3,
	jd: number
): Vec3 | null {
	const [cx, cy, cz] = centre;

	if (isSurface(anchor)) {
		const distance = kmToScene(effectiveRadiusKm(body.data) + (anchor.altitudeKm ?? 0));
		const [dx, dy, dz] = surfaceDirection(anchor.latitude, anchor.longitude, body.drawnRadii);
		// Without orientation metadata the body has no measured spin, so the
		// place is put on the unrotated sphere rather than nowhere.
		const q = body.orientation ? bodyQuaternion(body.orientation, jd, body.nutPrec) : null;
		if (!q) return [cx + dx * distance, cy + dy * distance, cz + dz * distance];
		const turned: Vec3 = [0, 0, 0];
		rotateByQuaternion(q, dx, dy, dz, turned, 0);
		return [cx + turned[0] * distance, cy + turned[1] * distance, cz + turned[2] * distance];
	}

	const offset = typeof anchor.offsetKm === 'function' ? anchor.offsetKm(jd) : anchor.offsetKm;
	// No offset at all is the body's centre; a trajectory that says nothing at
	// this date is nowhere.
	if (offset === null) return null;
	if (offset === undefined) return [cx, cy, cz];
	const [ox, oy, oz] = eclipticToScene(offset as Vec3);
	return [cx + ox, cy + oy, cz + oz];
}

/** World position of `anchor` in scene units, or null while its body is not
 *  loaded — which is normal: an embed can mark a place the reader has not
 *  travelled to yet — or while the body or a moving offset is nowhere at this
 *  date. */
export function resolveAnchor(anchor: Anchor, ctx: ContextManager, jd: number): Vec3 | null {
	const body = ctx.getBody(anchor.body);
	const centre = body && bodyCentre(body, ctx, jd);
	return centre ? placeAnchor(anchor, body, centre, jd) : null;
}

/** Unit vector from the body's centre toward the anchor, for the occlusion
 *  test; null when the anchor sits at the centre. */
export function anchorNormal(
	anchor: Anchor,
	world: Vec3,
	ctx: ContextManager,
	jd: number
): Vec3 | null {
	const body = ctx.getBody(anchor.body);
	const centre = body && bodyCentre(body, ctx, jd);
	if (!centre) return null;
	const dx = world[0] - centre[0];
	const dy = world[1] - centre[1];
	const dz = world[2] - centre[2];
	const length = Math.hypot(dx, dy, dz);
	if (length === 0) return null;
	return [dx / length, dy / length, dz / length];
}
