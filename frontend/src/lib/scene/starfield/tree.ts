/**
 * Geometry of the Milky Way render tree (`docs/export-format/extrasolar.md`).
 *
 * The tree is in parsecs with ICRS equatorial axes and the barycentre at the
 * origin. Child `k` of a node takes the +x side when bit 0 of `k` is set, +y
 * for bit 1 and +z for bit 2. A node holds the objects of its box that stay
 * visible from farthest away; its children hold the rest.
 */

import { AU_SCALE, equatorialToScene, sceneToEquatorial, type Vec3Like } from '$lib/math/units';

/** Astronomical units in one parsec. */
export const PC_AU = 648_000 / Math.PI;
/** Scene units in one parsec. */
export const PC_SCENE = PC_AU * AU_SCALE;

export type Vec3 = [number, number, number];

export function childCentre(centre: Vec3, half: number, k: number): Vec3 {
	const q = half / 2;
	return [centre[0] + (k & 1 ? q : -q), centre[1] + (k & 2 ? q : -q), centre[2] + (k & 4 ? q : -q)];
}

/** Distance from `p` to the nearest point of the box, 0 inside it. */
export function boxDistance(p: Vec3, centre: Vec3, half: number): number {
	const dx = Math.max(Math.abs(p[0] - centre[0]) - half, 0);
	const dy = Math.max(Math.abs(p[1] - centre[1]) - half, 0);
	const dz = Math.max(Math.abs(p[2] - centre[2]) - half, 0);
	return Math.hypot(dx, dy, dz);
}

/**
 * The apparent magnitude of the brightest object that a box can hold, seen
 * from the nearest point of the box. `range` is the largest visibility range
 * (pc) in the box, for `rangeLimitMag`. No object of the box is brighter.
 * -Infinity from inside the box.
 */
export function boxMagnitude(distance: number, range: number, rangeLimitMag: number): number {
	if (distance <= 0) return -Infinity;
	if (range <= 0) return Infinity;
	return rangeLimitMag + 5 * Math.log10(distance / range);
}

/** A scene position (barycentre origin, scene units) in the tree's frame. */
export function sceneToTree(x: number, y: number, z: number): Vec3 {
	const eq = sceneToEquatorial(x, y, z, { x: 0, y: 0, z: 0 });
	return [eq.x / PC_SCENE, eq.y / PC_SCENE, eq.z / PC_SCENE];
}

/** A tree position in the scene (barycentre origin, scene units). */
export function treeToScene<T extends Vec3Like>(x: number, y: number, z: number, out: T): T {
	return equatorialToScene(x * PC_SCENE, y * PC_SCENE, z * PC_SCENE, out);
}

/** A position from a record (ICRS degrees and a distance in pc) in the tree's frame. */
export function icrsToTree(raDeg: number, decDeg: number, distancePc: number): Vec3 {
	const ra = (raDeg * Math.PI) / 180;
	const dec = (decDeg * Math.PI) / 180;
	const c = Math.cos(dec) * distancePc;
	return [c * Math.cos(ra), c * Math.sin(ra), Math.sin(dec) * distancePc];
}

/**
 * Column-major elements of the matrix that takes tree positions (pc) to the
 * floating-origin scene. It scales to scene units, rotates to the ecliptic
 * and shifts by minus the focus.
 */
export function treeMatrixElements(focus: Vec3, out: number[]): number[] {
	const x = treeToScene(1, 0, 0, { x: 0, y: 0, z: 0 });
	const y = treeToScene(0, 1, 0, { x: 0, y: 0, z: 0 });
	const z = treeToScene(0, 0, 1, { x: 0, y: 0, z: 0 });
	out.length = 16;
	out[0] = x.x;
	out[1] = x.y;
	out[2] = x.z;
	out[3] = 0;
	out[4] = y.x;
	out[5] = y.y;
	out[6] = y.z;
	out[7] = 0;
	out[8] = z.x;
	out[9] = z.y;
	out[10] = z.z;
	out[11] = 0;
	out[12] = -focus[0];
	out[13] = -focus[1];
	out[14] = -focus[2];
	out[15] = 1;
	return out;
}
