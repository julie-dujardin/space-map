/**
 * Reading the scene rather than drawing on it: how far apart two places are,
 * and where on a body the Sun stands overhead. Both answer for the bodies as
 * the last frame placed them.
 */

import { SUN_ID } from '$lib/constants';
import { bodyQuaternion } from '$lib/math/orientation';
import type { LonLat } from '$lib/flatmap/geometry';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { resolveAnchor, rotateByQuaternion, type Anchor, type OffsetKm } from './anchor';
import { sceneToEcliptic } from './camera';

const DEG = 180 / Math.PI;

/** From one anchor to another, in kilometres on ecliptic J2000 axes; null
 *  while either is nowhere. */
export function anchorOffsetKm(
	a: Anchor,
	b: Anchor,
	ctx: ContextManager,
	jd: number
): OffsetKm | null {
	const from = resolveAnchor(a, ctx, jd);
	const to = resolveAnchor(b, ctx, jd);
	if (!from || !to) return null;
	// Subtracted in scene units first: the two ends can be an AU from the
	// origin and a kilometre from each other.
	return sceneToEcliptic([to[0] - from[0], to[1] - from[1], to[2] - from[2]]);
}

/** Kilometres between two anchors, or null while either is nowhere. */
export function anchorDistanceKm(
	a: Anchor,
	b: Anchor,
	ctx: ContextManager,
	jd: number
): number | null {
	const offset = anchorOffsetKm(a, b, ctx, jd);
	return offset && Math.hypot(...offset);
}

/** Body-fixed place a scene-frame direction from the body's centre points at:
 *  the inverse of the anchor's own lat/lon convention. */
export function directionToLonLat(x: number, y: number, z: number): LonLat {
	const length = Math.hypot(x, y, z);
	return {
		lon: Math.atan2(-z, x) * DEG,
		lat: Math.asin(Math.max(-1, Math.min(1, y / length))) * DEG
	};
}

/**
 * Where on `id` the Sun is at the zenith, in the frame a surface anchor is
 * placed in: an anchor there is on the lit side. A body with no measured spin
 * has no turning frame, and answers in the one its anchors fall back to. Null
 * for a body that is not loaded.
 */
export function subsolarPoint(id: string, ctx: ContextManager, jd: number): LonLat | null {
	const body = ctx.getBody(id);
	const sun = ctx.getBody(SUN_ID);
	if (!body || !sun || body === sun) return null;
	const toSun: [number, number, number] = [
		sun.position[0] - body.position[0],
		sun.position[1] - body.position[1],
		sun.position[2] - body.position[2]
	];
	if (body.orientation) {
		const turned = bodyQuaternion(body.orientation, jd, body.nutPrec).invert();
		rotateByQuaternion(turned, toSun[0], toSun[1], toSun[2], toSun, 0);
	}
	return directionToLonLat(toSun[0], toSun[1], toSun[2]);
}
