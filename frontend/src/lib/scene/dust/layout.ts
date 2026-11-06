/**
 * The layout of a sky map, and the law that places its slices along a ray. The
 * law is GLSL, in {@link DUST_RAY_GLSL}: the march and the lookup both include
 * it, so a read finds the slices the march wrote. `rayThroughBox` and the
 * steps of `columnBetween` (nest.ts) are the CPU form, for rays of the CPU.
 *
 * A texel of a sky map is one ray from the map's origin. It holds the column of
 * dust from the origin to a set of distances. Each layer holds four values, and
 * its last value is the first value of the next layer. So two neighbouring
 * values are always in one layer, and a read is one fetch. Value 0 is zero.
 *
 * A ray is cut to the box of the data. Slices are even in log(1 + s / scale),
 * with s the distance past the entry into the box. Inside the box the scale is
 * small, so slices grow with distance from the camera. Outside it the scale is
 * the distance to the entry, so slices are almost even across the disc.
 */

import { glslVec3 } from './glsl';

export const DUST_MAP_SIZE = 256;
/** Layers of a map, each one RGBA16F. */
export const DUST_MAP_LAYERS = 8;
/** Slices of a ray. Value 0 is the origin, so a map holds one value more. */
export const DUST_MAP_SLICES = 3 * DUST_MAP_LAYERS;
/** Steps of the march in each slice. */
export const DUST_SLICE_STEPS = 3;
/** Half extent (pc) of the box that holds all data: x, y and z of the nest. */
export const DUST_BOX: readonly [number, number, number] = [20_000, 20_000, 3_000];
/** Least slice scale (pc), for a ray that starts inside the box. */
export const DUST_NEAR_PC = 10;

/** Distance (pc) from a point to the box of the data, 0 inside it. */
export function distanceToBox(p: readonly [number, number, number]): number {
	return Math.hypot(
		Math.max(Math.abs(p[0]) - DUST_BOX[0], 0),
		Math.max(Math.abs(p[1]) - DUST_BOX[1], 0),
		Math.max(Math.abs(p[2]) - DUST_BOX[2], 0)
	);
}

export interface RaySpan {
	near: number;
	far: number;
}

/** Where a ray from `o` along the unit vector `d` is in the box. `near` is 0
 *  from inside. `far` is under `near` when the ray misses it. */
export function rayThroughBox(
	o: readonly [number, number, number],
	d: readonly [number, number, number]
): RaySpan {
	let near = 0;
	let far = Infinity;
	for (let i = 0; i < 3; i++) {
		const m = 1 / (d[i] + 1e-7);
		const n = m * o[i];
		const k = Math.abs(m) * DUST_BOX[i];
		near = Math.max(near, -n - k);
		far = Math.min(far, -n + k);
	}
	return { near, far };
}

/**
 * The slice law. `dustBoxSpan` gives the entry and exit of a ray in the box.
 * `dustSliceSpan` is the length of the ray in the log that slices are even in,
 * so a distance `r` is at `log(1 + (r - near) / scale) / dustSliceSpan`.
 */
export const DUST_RAY_GLSL = /* glsl */ `
highp vec2 dustBoxSpan(highp vec3 origin, highp vec3 d) {
	highp vec3 m = 1.0 / (d + 1e-7);
	highp vec3 n = m * origin;
	highp vec3 k = abs(m) * ${glslVec3(DUST_BOX)};
	highp vec3 lo = -n - k;
	highp vec3 hi = -n + k;
	return vec2(max(max(lo.x, lo.y), max(lo.z, 0.0)), min(hi.x, min(hi.y, hi.z)));
}
highp float dustSliceScale(highp float near) {
	return max(${DUST_NEAR_PC.toFixed(1)}, near);
}
highp float dustSliceSpan(highp float near, highp float far) {
	return log(1.0 + max(far - near, 1.0) / dustSliceScale(near));
}
`;
