/**
 * Reading the scene rather than drawing on it: how far apart two places are,
 * and where on a body the Sun stands overhead. Both answer for the date the
 * last frame placed the bodies at.
 */

import { SUN_ID } from '$lib/constants';
import { bodyQuaternion } from '$lib/math/orientation';
import { cartesianToSpherical } from '$lib/math/spherical';
import type { LonLat } from '$lib/flatmap/geometry';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { bodyCentre, resolveAnchor, type Anchor, type OffsetKm } from './anchor';
import { sceneToEcliptic } from './camera';

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

/**
 * Where on `id` the Sun is at the zenith, in the frame a surface anchor is
 * placed in: an anchor there is on the lit side. A body with no measured spin
 * has no turning frame, and answers in the one its anchors fall back to. Null
 * for a body that is not loaded or is nowhere at this date, and until the map
 * has read how it spins: the answer would be in a frame that may yet turn.
 */
export function subsolarPoint(id: string, ctx: ContextManager, jd: number): LonLat | null {
	const body = ctx.getBody(id);
	const sun = ctx.getBody(SUN_ID);
	if (!body || !sun || body === sun) return null;
	if (!body.orientation && !ctx.bodies.orientationRead.has(id)) return null;
	const centre = bodyCentre(body, ctx, jd);
	if (!centre) return null;
	// The identity is the unrotated sphere a spin-less body's anchors are on.
	const turn = body.orientation
		? bodyQuaternion(body.orientation, jd, body.nutPrec).toArray()
		: ([0, 0, 0, 1] as [number, number, number, number]);
	const { latitude, longitude, distance } = cartesianToSpherical(
		[sun.position[0], sun.position[1], sun.position[2]],
		[centre[0], centre[1], centre[2]],
		turn
	);
	return distance > 0 ? { lon: longitude, lat: latitude } : null;
}
