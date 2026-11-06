/**
 * The march that fills the glow's sky map. A ray holds its column of dust as it
 * goes, so the cut changes along it: a star's light is in the glow where the
 * star, seen through that dust, is under the limit.
 *
 * A ray has two spans. The first is inside the box of the dust, and its steps
 * restart at the entry, so a view from outside spends them on the disc. One
 * step's light takes the integral of the dust across the step (Hillaire 2016),
 * so brightness does not depend on step length. The second is the rest of the
 * ray out to the reach of the grid, where the halo and the Magellanic Clouds
 * are. It has no dust of its own, so it needs few steps.
 *
 * It draws through the `FullscreenPass` of the dust march.
 */

import type { WebGLRenderer } from 'three';
import { K_G, K_RGB, MAG_LN } from '$lib/scene/dust/extinction';
import { DUST_RAY_GLSL } from '$lib/scene/dust/layout';
import {
	FullscreenPass,
	densityGlsl,
	type NestTextures,
	type SkyMap,
	type VolumeTextures
} from '$lib/scene/dust/march';
import { octDirectionGlsl, octUvGlsl, type Vec3 } from '$lib/scene/dust/octahedral';
import type { GlowMetadata, GlowTierEntry } from './grid';
import { glowCurve, tableAxis } from './grid';
import { glslFloat } from '$lib/scene/dust/glsl';

/** Flux per sr from flux per pc³ along a ray in pc: (10 pc)². */
const AT_TEN_PC = 100;
/** The distance modulus per natural log of distance: 5 / ln 10. */
const MODULUS_LN = (2 / MAG_LN).toFixed(8);
/** Steps of the span past the box. */
export const OUTER_STEPS = 16;
/** Least scale (pc) of the outer span's steps. */
const OUTER_SCALE_PC = 100;

function fragmentShader(
	nest: NestTextures,
	meta: GlowMetadata,
	entry: GlowTierEntry,
	map: GlowShape
): string {
	const entries = meta.table.place_soft.length;
	const levels = nest.levels;
	const steps = map.steps.toFixed(1);
	const reach = entry.reach_pc;
	const table = tableAxis(meta);
	return /* glsl */ `#version 300 es
precision highp float;
precision highp sampler3D;
${levels.map((_, i) => `uniform sampler3D uLevel${i};`).join('\n')}
uniform sampler3D uA;
uniform sampler3D uB;
uniform vec4 uCurve[${entries}];
uniform vec3 uOrigin;
uniform float uCut;
uniform float uJitter;
layout(location = 0) out highp vec4 outLight;
${octDirectionGlsl(map.size)}
${DUST_RAY_GLSL}
${densityGlsl(levels)}
${octUvGlsl(entry.size, 'gridUv')}

// Flux per pc^3 and channel at p, of the stars fainter than cut.
vec3 light(vec3 p, float cut) {
	float r = length(p);
	vec3 uvw = vec3(gridUv(p / max(r, 1e-9)), log(1.0 + r / ${glslFloat(entry.scale_pc)}) / ${glslFloat(Math.log1p(entry.reach_pc / entry.scale_pc))});
	vec4 a = textureLod(uA, uvw, 0.0);
	vec4 b = textureLod(uB, uvw, 0.0);
	float at = clamp((cut + ${glslFloat(-table.first)}) * ${glslFloat(1 / table.step)}, 0.0, ${(entries - 1.001).toFixed(3)});
	int i = int(at);
	vec4 t = mix(uCurve[i], uCurve[i + 1], at - float(i));
	float L = dot(a, max(1.0 - abs(t.x - vec4(0.0, 1.0, 2.0, 3.0)), 0.0))
		+ dot(b.xyz, max(1.0 - abs(t.x - vec3(4.0, 5.0, 6.0)), 0.0));
	float tint = clamp(b.a, 1e-3, 1.0 - 1e-3);
	vec3 rgb = t.yzw * vec3((1.0 - tint) / ${glslFloat(1 - meta.neutral_tint)}, 1.0, tint / ${glslFloat(meta.neutral_tint)});
	return rgb * L / (rgb.r + rgb.g + rgb.b);
}

// Flux per pc^3 past the box. A model volume adds its own read here.
vec3 outerLight(vec3 p, float cut) {
	return light(p, cut);
}

// Where a ray is inside the reach of the grid, a sphere about the Sun.
vec2 reachSpan(vec3 o, vec3 d) {
	float b = dot(o, d);
	float c = dot(o, o) - ${glslFloat(reach * reach)};
	float h = b * b - c;
	if (h <= 0.0) return vec2(0.0);
	h = sqrt(h);
	return vec2(max(-b - h, 0.0), -b + h);
}

void main() {
	vec3 d = dustOctDirection(gl_FragCoord.xy / ${map.size.toFixed(1)});
	vec2 span = dustBoxSpan(uOrigin, d);
	float near = span.x;
	float far = span.y;
	bool hit = far > near;
	vec3 sum = vec3(0.0);
	float column = 0.0;
	vec3 seen = vec3(1.0);
	if (hit) {
		float scale = dustSliceScale(near);
		float lnq = dustSliceSpan(near, far) / ${steps};
		float q = exp(lnq);
		// e is s + scale, so ds = e * lnq for each step of the log.
		float e = scale * exp(uJitter * lnq);
		for (int i = 0; i < ${map.steps}; i++) {
			float s = near + e - scale;
			vec3 p = uOrigin + d * s;
			float ds = e * lnq;
			float rise = density(p) * ds;
			float cut = uCut - ${MODULUS_LN} * log(max(s, 1e-3) / 10.0) - ${K_G.toFixed(3)} * (column + 0.5 * rise);
			vec3 depth = rise * vec3(${K_RGB.map((k) => glslFloat(MAG_LN * k)).join(', ')});
			vec3 through = exp(-depth);
			// The mean of the light through the step. A thin step needs the series.
			vec3 mean = rise > 0.01 ? (1.0 - through) / depth : 1.0 - 0.5 * depth;
			sum += light(p, cut) * seen * mean * ds;
			seen *= through;
			column += rise;
			e *= q;
		}
	}
	// The outer span is the reach less the box, as one length u: the part
	// before the box, then the part behind it, which the box's column dims.
	vec2 sphere = reachSpan(uOrigin, d);
	float gap = hit ? far - near : 0.0;
	float before = hit ? max(near - sphere.x, 0.0) : 1e30;
	float outer = sphere.y - sphere.x - gap;
	if (outer > 1.0) {
		float start = sphere.x + (before > 0.0 ? 0.0 : gap);
		float scale = max(max(start, length(uOrigin)), ${OUTER_SCALE_PC.toFixed(1)});
		float lnq = log(1.0 + outer / scale) / ${OUTER_STEPS.toFixed(1)};
		float q = exp(lnq);
		float e = scale * exp(uJitter * lnq);
		for (int i = 0; i < ${OUTER_STEPS}; i++) {
			float u = e - scale;
			bool behind = u >= before;
			float s = sphere.x + u + (behind ? gap : 0.0);
			float cut = uCut - ${MODULUS_LN} * log(max(s, 1e-3) / 10.0) - ${K_G.toFixed(3)} * (behind ? column : 0.0);
			sum += outerLight(uOrigin + d * s, cut) * (behind ? seen : vec3(1.0)) * e * lnq;
			e *= q;
		}
	}
	outLight = vec4(sum * ${glslFloat(AT_TEN_PC / meta.texture_scale)}, 1.0);
}
`;
}

/** The size of a map and of its rays. */
export interface GlowShape {
	size: number;
	steps: number;
}

export class GlowMarch {
	private readonly pass: FullscreenPass;
	private readonly uOrigin: WebGLUniformLocation | null;
	private readonly uCut: WebGLUniformLocation | null;
	private readonly uJitter: WebGLUniformLocation | null;

	constructor(
		private readonly renderer: WebGLRenderer,
		private readonly nest: NestTextures,
		private readonly grid: VolumeTextures,
		meta: GlowMetadata,
		entry: GlowTierEntry,
		shape: GlowShape
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		this.pass = new FullscreenPass(renderer, fragmentShader(nest, meta, entry, shape));
		this.uOrigin = this.pass.uniform('uOrigin');
		this.uCut = this.pass.uniform('uCut');
		this.uJitter = this.pass.uniform('uJitter');
		this.pass.samplers([...nest.levels.map((_, i) => `uLevel${i}`), 'uA', 'uB']);
		gl.uniform4fv(this.pass.uniform('uCurve'), glowCurve(meta));
	}

	/**
	 * March `rows` rows of a map from `from`. The first pass writes; a later one
	 * blends in with `weight`, so the map stays the mean of its passes.
	 */
	run(
		map: SkyMap,
		origin: Vec3,
		cut: number,
		jitter: number,
		weight: number,
		from: number,
		rows: number
	): void {
		this.pass.run(
			map,
			(gl) => {
				const { state } = this.renderer;
				const textures = [...this.nest.textures, ...this.grid.textures];
				textures.forEach((texture, i) => {
					state.bindTexture(gl.TEXTURE_3D, texture, gl.TEXTURE0 + i);
				});
				gl.uniform3f(this.uOrigin, origin[0], origin[1], origin[2]);
				gl.uniform1f(this.uCut, cut);
				gl.uniform1f(this.uJitter, jitter);
			},
			weight,
			{ from, count: rows }
		);
	}

	dispose(): void {
		this.pass.dispose();
	}
}
