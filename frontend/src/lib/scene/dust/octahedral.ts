/**
 * The direction of a sky map texel, in GLSL. An octahedral map holds the whole
 * sphere in one square. +z, the north Galactic pole, is the centre of the
 * square, and the Galactic plane is the diamond |u| + |v| = 1.
 *
 * Bilinear reads cross the edge of the square, and the two sides of an edge are
 * not neighbours in the texture. So the map has a ring of one texel outside the
 * square that holds the rays past the edge.
 */

import { DUST_MAP_SIZE } from './layout';

export type Vec3 = [number, number, number];

/** The texture coordinate of a unit direction, on a map of `size` texels, as
 *  GLSL function `name`. */
export const octUvGlsl = (size: number, name = 'dustOctUv'): string => /* glsl */ `
highp vec2 ${name}(highp vec3 d) {
	highp float scale = 1.0 / (abs(d.x) + abs(d.y) + abs(d.z));
	highp vec2 q = d.xy * scale;
	highp vec2 side = step(vec2(0.0), q) * 2.0 - 1.0;
	if (d.z < 0.0) q = (1.0 - abs(q.yx)) * side;
	return (q * 0.5 + 0.5) * ${((size - 2) / size).toFixed(8)} + ${(1 / size).toFixed(8)};
}
`;

export const OCT_UV_GLSL = octUvGlsl(DUST_MAP_SIZE);

/** The unit direction of a texel's coordinate, on a map of `size` texels. */
export const octDirectionGlsl = (size: number): string => /* glsl */ `
highp vec3 dustOctDirection(highp vec2 uv) {
	highp vec2 q = ((uv - ${(1 / size).toFixed(8)}) * ${(size / (size - 2)).toFixed(8)} - 0.5) * 2.0;
	highp vec2 side = step(vec2(0.0), q) * 2.0 - 1.0;
	if (abs(q.x) > 1.0) q = vec2(2.0 * side.x - q.x, -q.y);
	side = step(vec2(0.0), q) * 2.0 - 1.0;
	if (abs(q.y) > 1.0) q = vec2(-q.x, 2.0 * side.y - q.y);
	side = step(vec2(0.0), q) * 2.0 - 1.0;
	highp float z = 1.0 - abs(q.x) - abs(q.y);
	if (z < 0.0) q = (1.0 - abs(q.yx)) * side;
	return normalize(vec3(q, z));
}
`;

export const OCT_DIRECTION_GLSL = octDirectionGlsl(DUST_MAP_SIZE);
