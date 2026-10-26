/**
 * Where a link to a planetary system puts the camera: about four outer
 * orbits from the target, 45° above the system's plane, on the side of the
 * Sun. Most systems are edge-on as seen from the Sun, so from home the
 * orbits would show as lines.
 */

import { AU_SCALE } from '$lib/math/units';
import { cartesianToSpherical } from '$lib/math/spherical';
import type { Vec3 } from '$lib/scene/animation/math';

/** Camera distance of a link, in outer orbits. */
export const FRAME_OUTER_ORBITS = 4;
/** Camera height above the system's plane. */
export const FRAME_ELEVATION_DEG = 45;

/** A camera place about a body: scene units, and degrees in scene axes. */
export interface SystemView {
	distance: number;
	latitude: number;
	longitude: number;
}

const DEG = Math.PI / 180;

/** The unit normal of an orbit's plane in scene axes, along its angular momentum. */
export function orbitNormal(i: number, om: number): Vec3 {
	// Ecliptic (sin i sin Ω, −sin i cos Ω, cos i), in the scene's (x, z, −y).
	return [
		Math.sin(i * DEG) * Math.sin(om * DEG),
		Math.cos(i * DEG),
		Math.sin(i * DEG) * Math.cos(om * DEG)
	];
}

/**
 * The camera's direction from the target: `elevationDeg` above the plane of
 * `normal`, toward the barycentre seen from `host` (scene units), and on the
 * barycentre's side of the plane. A plane face-on to the barycentre turns
 * toward the scene's +x.
 */
export function frameDirection(
	host: Readonly<Vec3>,
	normal: Readonly<Vec3>,
	elevationDeg: number
): Vec3 {
	const len = Math.hypot(host[0], host[1], host[2]);
	const s: Vec3 = len > 0 ? [-host[0] / len, -host[1] / len, -host[2] / len] : [1, 0, 0];
	const along = s[0] * normal[0] + s[1] * normal[1] + s[2] * normal[2];
	const sign = along < 0 ? -1 : 1;
	let p: Vec3 = [s[0] - along * normal[0], s[1] - along * normal[1], s[2] - along * normal[2]];
	let plen = Math.hypot(p[0], p[1], p[2]);
	if (plen < 1e-9) {
		const x = normal[0];
		p = [1 - x * normal[0], -x * normal[1], -x * normal[2]];
		plen = Math.hypot(p[0], p[1], p[2]);
		if (plen < 1e-9) {
			p = [0, 0, 1];
			plen = 1;
		}
	}
	const c = Math.cos(elevationDeg * DEG);
	const h = Math.sin(elevationDeg * DEG) * sign;
	return [
		(c * p[0]) / plen + h * normal[0],
		(c * p[1]) / plen + h * normal[1],
		(c * p[2]) / plen + h * normal[2]
	];
}

/** The view of a link to a system whose outer orbit is `outerAU`, the target
 *  in the system (its host or one of its planets). */
export function systemView(
	host: Readonly<Vec3>,
	normal: Readonly<Vec3>,
	outerAU: number
): SystemView {
	const distance = FRAME_OUTER_ORBITS * outerAU * AU_SCALE;
	const d = frameDirection(host, normal, FRAME_ELEVATION_DEG);
	const { latitude, longitude } = cartesianToSpherical([d[0], d[1], d[2]], [0, 0, 0]);
	return { distance, latitude, longitude };
}
