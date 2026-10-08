/**
 * The measures of a scene. They give the distance between two places, the
 * place on a body where the Sun is overhead, and the sunlight that reaches a
 * body. The functions that take a scene answer for the date of the last frame.
 */

import { SUN_ID } from '$lib/constants';
import { bodyQuaternion } from '$lib/math/orientation';
import { cartesianToSpherical } from '$lib/math/spherical';
import type { LonLat } from '$lib/flatmap/geometry';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import type { Vec3 } from '$lib/scene/animation/math';
import { sunInView } from '$lib/scene/objects/surface/eclipse-shadow';
import { bodyCentre, resolveAnchor, type Anchor, type AnchorBody, type OffsetKm } from './anchor';
import { sceneToEcliptic } from './camera';
import { planeBasis } from './geometry';

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
 * Where on `body` the Sun is at the zenith, in the frame a surface anchor is
 * placed in: an anchor there is on the lit side. A body with no measured spin
 * has no turning frame, and answers in the one its anchors fall back to.
 */
export function subsolarAt(body: AnchorBody, centre: Vec3, sun: Vec3, jd: number): LonLat | null {
	// The identity is the unrotated sphere a spin-less body's anchors are on.
	const turn = body.orientation
		? bodyQuaternion(body.orientation, jd, body.nutPrec).toArray()
		: ([0, 0, 0, 1] as [number, number, number, number]);
	const { latitude, longitude, distance } = cartesianToSpherical(
		[sun[0], sun[1], sun[2]],
		[centre[0], centre[1], centre[2]],
		turn
	);
	return distance > 0 ? { lon: longitude, lat: latitude } : null;
}

/**
 * {@link subsolarAt} for a body of the scene. Null for a body that is not
 * loaded or is nowhere at this date, and until the map has read how it spins:
 * the answer would be in a frame that may yet turn.
 */
export function subsolarPoint(id: string, ctx: ContextManager, jd: number): LonLat | null {
	const body = ctx.getBody(id);
	const sun = ctx.getBody(SUN_ID);
	if (!body || !sun || body === sun) return null;
	if (!body.orientation && !ctx.bodies.orientationRead.has(id)) return null;
	const centre = bodyCentre(body, ctx, jd);
	const sunCentre = bodyCentre(sun, ctx, jd);
	return centre && sunCentre && subsolarAt(body, centre, sunCentre, jd);
}

/** A ball that can hide the Sun, or the Sun itself. */
export interface Ball {
	/** From the centre of the body that the light falls on. */
	centre: OffsetKm;
	radiusKm: number;
}

/** Points on the sunlit face that {@link sunlightAt} takes the mean of. */
const SUNLIGHT_SAMPLES = 1024;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

/**
 * The part of the light of the Sun that reaches a ball of `radiusKm` at the
 * origin, from 0 to 1. It is the mean of {@link sunInView} over the face that
 * the Sun is on, with each point counted by the area it shows to the Sun. The
 * map shades a body with the same formula and the same balls.
 */
export function sunlightAt(radiusKm: number, sun: Ball, occluders: readonly Ball[]): number {
	const sunKm = Math.hypot(...sun.centre);
	const aSun = Math.asin(Math.min(sun.radiusKm / sunKm, 1));
	if (!(aSun > 0)) return 1;
	const toSun = sun.centre.map((km) => km / sunKm);
	const along = (v: OffsetKm) => v[0] * toSun[0] + v[1] * toSun[1] + v[2] * toSun[2];
	// Keeps a ball when its shadow can be on the body. The points decide the rest.
	const near = occluders.filter(({ centre, radiusKm: r }) => {
		const ahead = along(centre);
		const aside = Math.sqrt(Math.max(Math.hypot(...centre) ** 2 - ahead ** 2, 0));
		return ahead > -(radiusKm + r) && aside < radiusKm + r + 2 * aSun * (ahead + radiusKm);
	});
	if (near.length === 0) return 1;

	const [u, v] = planeBasis(sun.centre);
	let sum = 0;
	for (let i = 0; i < SUNLIGHT_SAMPLES; i++) {
		// A sunflower spiral. It gives each point the same area of the disc.
		const rho = Math.sqrt((i + 0.5) / SUNLIGHT_SAMPLES);
		const x = radiusKm * rho * Math.cos(i * GOLDEN_ANGLE);
		const y = radiusKm * rho * Math.sin(i * GOLDEN_ANGLE);
		const z = radiusKm * Math.sqrt(1 - rho * rho);
		let lit = 1;
		for (const { centre, radiusKm: r } of near) {
			const to: OffsetKm = [
				centre[0] - x * u[0] - y * v[0] - z * toSun[0],
				centre[1] - x * u[1] - y * v[1] - z * toSun[1],
				centre[2] - x * u[2] - y * v[2] - z * toSun[2]
			];
			const km = Math.hypot(...to);
			const sep = Math.acos(Math.max(-1, Math.min(1, along(to) / km)));
			lit *= sunInView(aSun, Math.asin(Math.min(r / km, 1)), sep);
			if (lit === 0) break;
		}
		sum += lit;
	}
	return sum / SUNLIGHT_SAMPLES;
}
