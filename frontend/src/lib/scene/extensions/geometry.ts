/**
 * Turning a shape into points the map can draw. Everything here is kilometres
 * on ecliptic J2000 axes, the same numbers a host hands to a polyline, so a
 * ring made here can be edited and passed back.
 *
 * The flat map's cousins of these live in `$lib/flatmap/geometry`, where a
 * shape is longitude and latitude and the answer is an SVG path.
 */

import { ShapeUtils, Vector2 } from 'three';
import type { OffsetKm } from './anchor';

/** Two unit vectors across the plane at right angles to `normal` and to each
 *  other. Any direction at all does for the first one as long as it is not the
 *  normal itself, so the ecliptic pole stands in wherever the normal is. */
export function planeBasis(normal: OffsetKm): [OffsetKm, OffsetKm] {
	const length = Math.hypot(normal[0], normal[1], normal[2]);
	const n: OffsetKm =
		length > 0 ? [normal[0] / length, normal[1] / length, normal[2] / length] : [0, 0, 1];
	const aside: OffsetKm = Math.abs(n[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
	const u = cross(aside, n);
	const uLength = Math.hypot(u[0], u[1], u[2]);
	const a: OffsetKm = [u[0] / uLength, u[1] / uLength, u[2] / uLength];
	return [a, cross(n, a)];
}

function cross(a: OffsetKm, b: OffsetKm): OffsetKm {
	return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

export interface CirclePointsOptions {
	/** Which way the circle's plane faces. The ecliptic north pole when left
	 *  out, which draws a ring in the plane the planets go round in. */
	normal?: OffsetKm;
	/** Points round the ring. */
	steps?: number;
}

/** A ring of `steps` points at `radiusKm` from the origin, in the plane at
 *  right angles to `normal`. */
export function circlePoints(radiusKm: number, options: CirclePointsOptions = {}): OffsetKm[] {
	const [a, b] = planeBasis(options.normal ?? [0, 0, 1]);
	const steps = Math.max(3, Math.round(options.steps ?? 128));
	const ring: OffsetKm[] = [];
	for (let i = 0; i < steps; i++) {
		const θ = (2 * Math.PI * i) / steps;
		const c = Math.cos(θ) * radiusKm;
		const s = Math.sin(θ) * radiusKm;
		ring.push([a[0] * c + b[0] * s, a[1] * c + b[1] * s, a[2] * c + b[2] * s]);
	}
	return ring;
}

/**
 * Triangle indices for a filled outline, three per triangle.
 *
 * The outline is flattened onto the plane it lies closest to before it is cut
 * up, so a ring given in three dimensions fills correctly however it is
 * turned. An outline whose points are nowhere near one plane fills as its
 * shadow on that plane does, which is the best a flat fill can mean.
 */
export function triangulate(points: readonly OffsetKm[]): number[] {
	if (points.length < 3) return [];
	const [a, b] = planeBasis(newellNormal(points));
	const flat = points.map(
		(p) =>
			new Vector2(p[0] * a[0] + p[1] * a[1] + p[2] * a[2], p[0] * b[0] + p[1] * b[1] + p[2] * b[2])
	);
	return ShapeUtils.triangulateShape(flat, []).flat();
}

/** The plane a run of points lies closest to, by Newell's method: it survives
 *  points that are collinear or repeated, which a normal from the first three
 *  does not. */
export function newellNormal(points: readonly OffsetKm[]): OffsetKm {
	let x = 0;
	let y = 0;
	let z = 0;
	for (let i = 0; i < points.length; i++) {
		const p = points[i];
		const q = points[(i + 1) % points.length];
		x += (p[1] - q[1]) * (p[2] + q[2]);
		y += (p[2] - q[2]) * (p[0] + q[0]);
		z += (p[0] - q[0]) * (p[1] + q[1]);
	}
	return Math.hypot(x, y, z) > 0 ? [x, y, z] : [0, 0, 1];
}

/** A place on the sphere a fraction of the way from `a` to `b`, both unit
 *  vectors. What a fan filling a surface shape is built out of: its rows have
 *  to bend with the body rather than cut through it. */
export function slerpDirection(
	a: readonly number[],
	b: readonly number[],
	t: number
): [number, number, number] {
	const dot = Math.min(1, Math.max(-1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
	const angle = Math.acos(dot);
	// Antipodal ends have no short way round, and touching ends need no
	// interpolation; both fall back to a straight mix, renormalised below.
	if (angle < 1e-9 || Math.PI - angle < 1e-9) {
		return unit([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]);
	}
	const sin = Math.sin(angle);
	const ka = Math.sin((1 - t) * angle) / sin;
	const kb = Math.sin(t * angle) / sin;
	return [a[0] * ka + b[0] * kb, a[1] * ka + b[1] * kb, a[2] * ka + b[2] * kb];
}

function unit(v: [number, number, number]): [number, number, number] {
	const length = Math.hypot(v[0], v[1], v[2]);
	return length > 0 ? [v[0] / length, v[1] / length, v[2] / length] : [0, 0, 1];
}

/** Mean direction of a run of unit vectors, as the middle of a shape drawn on
 *  a sphere. Falls back to the first one for a ring that surrounds its body
 *  evenly enough to have no middle. */
export function meanDirection(dirs: Float64Array, count: number): [number, number, number] {
	let x = 0;
	let y = 0;
	let z = 0;
	for (let i = 0; i < count; i++) {
		x += dirs[i * 3];
		y += dirs[i * 3 + 1];
		z += dirs[i * 3 + 2];
	}
	if (Math.hypot(x, y, z) < 1e-9) return [dirs[0], dirs[1], dirs[2]];
	return unit([x, y, z]);
}
