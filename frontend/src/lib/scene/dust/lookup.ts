/** The read of a sky map in a star's vertex shader. It is one texture fetch. */

import { DUST_MAP_LAYERS, DUST_MAP_SLICES, DUST_RAY_GLSL } from './layout';
import { OCT_UV_GLSL } from './octahedral';

/** `dustColumn(map, origin, at)`: the column (mag at 550 nm) from the map's
 *  origin to a point `at` from it. All in pc on nest axes. */
export const DUST_COLUMN_GLSL = /* glsl */ `
${DUST_RAY_GLSL}
${OCT_UV_GLSL}
highp float dustColumn(highp sampler2DArray map, highp vec3 origin, highp vec3 at) {
	highp float r = length(at);
	highp vec3 d = r > 1e-6 ? at / r : vec3(0.0, 0.0, 1.0);
	highp vec2 span = dustBoxSpan(origin, d);
	highp float place = log(1.0 + max(r - span.x, 0.0) / dustSliceScale(span.x)) / dustSliceSpan(span.x, span.y);
	highp float slice = min(place, 1.0) * ${DUST_MAP_SLICES.toFixed(1)};
	highp float layer = min(floor(slice / 3.0), ${(DUST_MAP_LAYERS - 1).toFixed(1)});
	highp vec4 share = max(1.0 - abs(slice - 3.0 * layer - vec4(0.0, 1.0, 2.0, 3.0)), 0.0);
	return dot(textureLod(map, vec3(dustOctUv(d), layer), 0.0), share);
}
`;
