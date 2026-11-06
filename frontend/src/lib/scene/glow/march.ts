/**
 * The march that draws the glow. A ray holds its column of dust as it goes, so
 * the cut changes along it: a star's light is in the glow where the star, seen
 * through that dust, is under the limit. Model light adds the light the
 * catalogue lacks, so the whole Galaxy draws from any place.
 *
 * A ray has two spans. The first is inside the box of the dust and of the
 * model's inner box, and its steps restart at the entry, so a view from outside
 * spends them on the disc. One step's light takes the integral of the dust
 * across the step (Hillaire 2016), so brightness does not depend on step
 * length. The second is the rest of the ray out to the reach of the grid, where
 * the halo is. It has no dust of its own, so it needs few steps. Its steps grow
 * with distance, so the Magellanic Clouds have boxes (`clouds.ts`) where a ray
 * takes steps of its own, and the second span skips them.
 *
 * Light that is not starlight (`emission.ts`) adds in the first span, where the
 * dust is: H-alpha at the lines' own K, and starlight that dust scatters at the
 * stars'.
 *
 * A sample reads the light grid at the width of what it stands for across the
 * Sun's line of sight: the part of its step across it and its texel, to a few
 * texels. Where that is wider than a cell of the grid, it reads a coarse copy
 * (`prefilter.ts`), so a small bright cell does not come and go between poses.
 * Elsewhere it reads the grid itself.
 *
 * Two kinds of target. The screen target holds one ray per texel from the
 * camera, so the glow is a function of the camera's pose alone. Its jitter is
 * fixed per pixel and its place in the texel per pass, so a pose always gives
 * the same pixels, and the passes together cover each texel. The octahedral
 * sky map holds the emission alone from the Sun, for the sky inside the solar
 * system, where the skybox holds none of it.
 *
 * Alpha is 0: nothing reads it.
 *
 * It draws through the `FullscreenPass` of the dust march.
 */

import type { WebGLRenderer } from 'three';
import { K_G, K_RGB, MAG_LN } from '$lib/scene/dust/extinction';
import { DUST_BOX, DUST_RAY_GLSL } from '$lib/scene/dust/layout';
import {
	FullscreenPass,
	densityGlsl,
	type NestTextures,
	type PassTarget,
	type VolumeTextures
} from '$lib/scene/dust/march';
import { octDirectionGlsl, octUvGlsl, type Vec3 } from '$lib/scene/dust/octahedral';
import type { GlowGridTier, GlowMetadata, GlowTierEntry } from './grid';
import { glowCurve, tableAxis } from './grid';
import {
	NO_PARTS,
	emissionGlsl,
	emissionSamplers,
	type EmissionParts,
	type EmissionTextures,
	type GlowEmission
} from './emission';
import type { CloudBox } from './clouds';
import { glowDensityGlsl, type FarDustEntry } from './far-dust';
import { modelColours, modelGlsl, type GlowModel } from './model';
import { coarseUniforms, type CoarseLayout } from './prefilter';
import { glslFloat, glslVec3 } from '$lib/scene/dust/glsl';

/** Flux per sr from flux per pc³ along a ray in pc: (10 pc)². */
const AT_TEN_PC = 100;
/** The distance modulus per natural log of distance: 5 / ln 10. */
const MODULUS_LN = (2 / MAG_LN).toFixed(8);
/** Steps of the span past the box. */
export const OUTER_STEPS = 16;
/** Steps through a Cloud's box, from the steps of the first span: from far a
 *  Cloud is a few pixels, from inside it is the sky. */
export function cloudSteps(steps: number): number {
	return Math.max(Math.round(steps / 3), 8);
}
/**
 * Most width of a read of the grid, in texels of the target. A read averages
 * as far across the ray as along it. Wider, it moves light out of the dust
 * lane and lifts the plane's light over it. Narrower, the steps near the Sun
 * flicker again.
 */
const READ_TEXELS = 4;
/** Least scale (pc) of the outer span's steps. A camera far outside, as in a
 *  Magellanic Cloud, has light about it, so the steps start fine there too. */
const OUTER_SCALE_PC = 100;

/** Which target a program fills: the screen, or an octahedral sky map. */
export type MapKind = 'screen' | 'sky';

/** What a program marches: everything, or the emission alone. */
interface MarchLight {
	stars: boolean;
	parts: EmissionParts;
	emission: GlowEmission | null;
}

function directionGlsl(kind: MapKind, size: number): string {
	if (kind === 'sky') {
		return `${octDirectionGlsl(size)}
uniform float uJitter;
vec3 rayDirection() { return dustOctDirection(gl_FragCoord.xy / ${size.toFixed(1)}); }
float rayJitter() { return uJitter; }
float pixelAngle(vec3 d) { return 0.0; }`;
	}
	return /* glsl */ `
uniform highp mat3 uRayAxes;
uniform highp vec4 uLens;
uniform highp vec2 uTexel;
uniform highp vec2 uSubTexel;
uniform float uJitter;
vec3 rayDirection() {
	highp vec2 q = (gl_FragCoord.xy + uSubTexel) * uTexel * 2.0 - 1.0;
	return normalize(uRayAxes * vec3((q + uLens.zw) * uLens.xy, -1.0));
}
// The jitter is fixed per texel, so a pose always gives the same pixels: a float
// hash (Hoskins 2014, "Hash without Sine"), white noise with no lines, plus the
// pass's offset. So pass 0 alone is close to the mean of all passes over a
// view, and the composite blurs out the rest. A uint hash converts to float
// wrong on some drivers.
float rayJitter() {
	highp vec3 p = fract(vec3(floor(gl_FragCoord.xyx)) * 0.1031);
	p += dot(p, p.yzx + 33.33);
	return fract((p.x + p.y) * p.z + uJitter);
}
// The angle of a texel of the target along the ray d.
float pixelAngle(vec3 d) {
	return 2.0 * uLens.y * uTexel.y * max(-dot(d, uRayAxes[2]), 0.0);
}`;
}

/**
 * GLSL of `glowSpan`, where a ray is in the first span. With a model it is the
 * box that holds the dust's and the model's inner box, so the model's disc past
 * the dust box gets the fine steps too. Without one it is the dust's box.
 */
function spanGlsl(model: GlowModel | null): string {
	if (!model)
		return 'highp vec2 glowSpan(highp vec3 o, highp vec3 d) { return dustBoxSpan(o, d); }';
	const { centre_pc: c, boxes } = model;
	const half = boxes.inner.half_extent_pc;
	const lo = [0, 1, 2].map((i) => Math.min(-DUST_BOX[i], c[i] - half[i]));
	const hi = [0, 1, 2].map((i) => Math.max(DUST_BOX[i], c[i] + half[i]));
	return /* glsl */ `
highp vec2 glowSpan(highp vec3 o, highp vec3 d) {
	highp vec3 m = 1.0 / (d + 1e-7);
	highp vec3 a = (${glslVec3(lo)} - o) * m;
	highp vec3 b = (${glslVec3(hi)} - o) * m;
	highp vec3 lo = min(a, b);
	highp vec3 hi = max(a, b);
	return vec2(max(max(lo.x, lo.y), max(lo.z, 0.0)), min(hi.x, min(hi.y, hi.z)));
}`;
}

/** The rest of the ray past the first span, out to the grid's reach. The emission
 *  alone has none: it is all where the dust is. */
function outerSpanGlsl(clouds: number): string {
	return /* glsl */ `
	// The outer span is the reach less the box, as one length u: the part
	// before the box, then the part behind it, which the box's column dims.
	vec2 sphere = reachSpan(uOrigin, d);
	float gap = hit ? far - near : 0.0;
	float before = hit ? max(near - sphere.x, 0.0) : 1e30;
	float outer = sphere.y - sphere.x - gap;
	if (outer > 1.0) {
		float start = sphere.x + (before > 0.0 ? 0.0 : gap);
		float scale = max(start, ${OUTER_SCALE_PC.toFixed(1)});
		float lnq = log(1.0 + outer / scale) / ${OUTER_STEPS.toFixed(1)};
		float q = exp(lnq);
		float e = scale * exp(jitter * lnq);
		for (int i = 0; i < ${OUTER_STEPS}; i++) {
			float u = e - scale;
			bool behind = u >= before;
			float s = sphere.x + u + (behind ? gap : 0.0);
			vec3 p = uOrigin + d * s;
			float cut = uCut - ${MODULUS_LN} * log(max(s, 1e-3) / 10.0) - ${K_G.toFixed(3)} * (behind ? column : 0.0);
			if (!inCloud(p, ${clouds})) {
				vec3 gain = (behind ? seen : vec3(1.0)) * e * lnq;
				sum += glowLight(p, cut, modelLight(p), d, s * pixel, e * lnq) * gain;
			}
			e *= q;
		}
	}
`;
}

/**
 * GLSL of `inCloud(p, n)`, whether p is in one of the first n Cloud boxes, and
 * of the march through each box with `steps` steps of its own. A box's steps
 * skip the first span, where that span's steps hold the light, and the boxes
 * before it, so no light counts twice. Behind the first span the box's light
 * takes that span's dust.
 */
function cloudGlsl(
	clouds: readonly CloudBox[],
	steps: number
): { functions: string; march: string } {
	const test = clouds.map(
		({ lo, hi }, k) =>
			`(n > ${k} && all(greaterThanEqual(p, ${glslVec3(lo)})) && all(lessThanEqual(p, ${glslVec3(hi)})))`
	);
	const functions = /* glsl */ `
bool inCloud(highp vec3 p, int n) { return ${test.length ? test.join(' || ') : 'false'}; }

// Where a ray from o is in the box from lo to hi.
highp vec2 boxSpan(highp vec3 o, highp vec3 d, highp vec3 lo, highp vec3 hi) {
	highp vec3 m = 1.0 / (d + 1e-7);
	highp vec3 a = (lo - o) * m;
	highp vec3 b = (hi - o) * m;
	highp vec3 near = min(a, b);
	highp vec3 far = max(a, b);
	return vec2(max(max(near.x, near.y), max(near.z, 0.0)), min(far.x, min(far.y, far.z)));
}`;
	const march = clouds
		.map(
			({ lo, hi }, k) => /* glsl */ `
	{
		vec2 box = boxSpan(uOrigin, d, ${glslVec3(lo)}, ${glslVec3(hi)});
		if (box.y > box.x) {
			float scale = max(box.x, ${OUTER_SCALE_PC.toFixed(1)});
			float lnq = log(1.0 + (box.y - box.x) / scale) / ${steps.toFixed(1)};
			float q = exp(lnq);
			float e = scale * exp(jitter * lnq);
			for (int i = 0; i < ${steps}; i++) {
				float s = box.x + e - scale;
				vec3 p = uOrigin + d * s;
				bool first = hit && s > near && s < far;
				if (!first && !inCloud(p, ${k})) {
					bool behind = hit && s >= far;
					float cut = uCut - ${MODULUS_LN} * log(max(s, 1e-3) / 10.0) - ${K_G.toFixed(3)} * (behind ? column : 0.0);
					vec3 gain = (behind ? seen : vec3(1.0)) * e * lnq;
					sum += glowLight(p, cut, modelLight(p), d, s * pixel, e * lnq) * gain;
				}
				e *= q;
			}
		}
	}`
		)
		.join('');
	return { functions, march };
}

/** The lines of a step of the first span that read and add its light. */
function stepGlsl({ stars, parts }: MarchLight): { density: string; light: string } {
	const density = parts.scatter
		? `float rho = glowDensity(p);
			float rise = rho * ds;`
		: 'float rise = glowDensity(p) * ds;';
	const scattered = parts.scatter ? 'scatteredLight(p, rho)' : '';
	const model = stars
		? `modelLight(p)${scattered ? ` + ${scattered}` : ''}`
		: scattered || 'vec3(0.0)';
	const lines = parts.halpha ? 'sum += lineLight(p, column, rise, ds);' : '';
	return {
		density,
		light: `vec3 model = ${model};
			vec3 gain = seen * mean * ds;
			${stars ? 'sum += glowLight(p, cut, model, d, s * pixel, ds) * gain;' : 'sum += model * gain;'}
			${lines}`
	};
}

/**
 * GLSL that sets `a` and `b`, the grid's two texels at `uvw`, read at the width
 * that the sample at p stands for, squared (`wide2`, pc²). Level 0 is the grid
 * itself, and level k is coarse copy k, with about 2^k times its cell. A read
 * between two levels mixes them, and the tint takes the weight of the light it
 * is the tint of. Without copies it reads the grid.
 */
function gridReadGlsl(coarse: CoarseLayout | null, size: number): string {
	const fine = /* glsl */ `a = textureLod(uA, uvw, 0.0);
		b = textureLod(uB, uvw, 0.0);`;
	if (!coarse) return fine;
	const top = coarse.levels.length;
	// A cell is c (|x| + |y| + |z|)^1.5 / r^1.5 radians wide, c = 2 / (size - 2),
	// so (width / (r × cell))² is wide2 · r / (c² (|x| + |y| + |z|)³).
	return /* glsl */ `
	float l1 = dot(abs(p), vec3(1.0));
	float over = wide2 * r;
	float cell = ${glslFloat((2 / (size - 2)) ** 2)} * l1 * l1 * l1;
	float level = 0.0;
	if (uCoarseOn && over > cell) level = 0.5 * log2(over / cell);
	if (level < 1.0) {
		${fine}
	}
	if (level > 0.0) {
		float at = min(level, ${top.toFixed(1)});
		int k = int(at);
		float f = at - float(k);
		vec4 box = uCoarse[min(k, ${top - 1})];
		vec3 above = vec3(uvw.xy * box.xy + box.zw, uvw.z);
		vec4 ua = textureLod(uCoarseA, above, 0.0);
		vec4 ub = textureLod(uCoarseB, above, 0.0);
		if (k > 0) {
			box = uCoarse[k - 1];
			vec3 below = vec3(uvw.xy * box.xy + box.zw, uvw.z);
			a = textureLod(uCoarseA, below, 0.0);
			b = textureLod(uCoarseB, below, 0.0);
		}
		float wa = a.a * (1.0 - f);
		float wu = ua.a * f;
		float tint = wa + wu > 0.0 ? (wa * b.a + wu * ub.a) / (wa + wu) : mix(b.a, ub.a, f);
		a = mix(a, ua, f);
		b = vec4(mix(b.xyz, ub.xyz, f), tint);
	}`;
}

function fragmentShader(
	nest: NestTextures,
	meta: GlowMetadata,
	entry: GlowTierEntry,
	steps: number,
	kind: MapKind,
	size: number,
	far: FarDustEntry | null,
	marched: MarchLight,
	tier: GlowGridTier,
	clouds: readonly CloudBox[],
	coarse: CoarseLayout | null
): string {
	const entries = meta.table.place_soft.length;
	const levels = nest.levels;
	const reach = entry.reach_pc;
	const table = tableAxis(meta);
	const step = stepGlsl(marched);
	const emission = marched.emission
		? emissionGlsl(marched.emission, marched.parts, tier, meta.texture_scale)
		: '';
	const cloud = cloudGlsl(marched.stars ? clouds : [], cloudSteps(steps));
	return /* glsl */ `#version 300 es
precision highp float;
precision highp sampler3D;
${levels.map((_, i) => `uniform sampler3D uLevel${i};`).join('\n')}
uniform sampler3D uA;
uniform sampler3D uB;
${coarse ? `uniform sampler3D uCoarseA;\nuniform sampler3D uCoarseB;\nuniform vec4 uCoarse[${coarse.levels.length}];\nuniform bool uCoarseOn;` : ''}
uniform vec4 uCurve[${entries}];
uniform vec3 uOrigin;
uniform float uCut;
layout(location = 0) out highp vec4 outLight;
${directionGlsl(kind, size)}
${DUST_RAY_GLSL}
${spanGlsl(meta.model ?? null)}
${densityGlsl(levels)}
${glowDensityGlsl(levels, far)}
${octUvGlsl(entry.size, 'gridUv')}
${modelGlsl(meta.model ?? null, meta.texture_scale)}
${emission}
${cloud.functions}

// Flux per pc^3 and channel at p, of the stars fainter than cut, read at the
// width across the Sun's line of sight whose square is wide2 (pc²).
vec3 light(vec3 p, float cut, float wide2) {
	float r = length(p);
	vec3 uvw = vec3(gridUv(p / max(r, 1e-9)), log(1.0 + r / ${glslFloat(entry.scale_pc)}) / ${glslFloat(Math.log1p(entry.reach_pc / entry.scale_pc))});
	vec4 a = vec4(0.0);
	vec4 b = vec4(0.0);
	${gridReadGlsl(coarse, entry.size)}
	float at = clamp((cut + ${glslFloat(-table.first)}) * ${glslFloat(1 / table.step)}, 0.0, ${(entries - 1.001).toFixed(3)});
	int i = int(at);
	vec4 t = mix(uCurve[i], uCurve[i + 1], at - float(i));
	float L = dot(a, max(1.0 - abs(t.x - vec4(0.0, 1.0, 2.0, 3.0)), 0.0))
		+ dot(b.xyz, max(1.0 - abs(t.x - vec3(4.0, 5.0, 6.0)), 0.0));
	float tint = clamp(b.a, 1e-3, 1.0 - 1e-3);
	vec3 rgb = t.yzw * vec3((1.0 - tint) / ${glslFloat(1 - meta.neutral_tint)}, 1.0, tint / ${glslFloat(meta.neutral_tint)});
	return rgb * L / (rgb.r + rgb.g + rgb.b);
}

// The catalogue's light fades out with distance from the Sun, so its fetches
// run only where it holds some. A sample on the ray d stands for its step ds
// and its texel, texel pc wide. Across the Sun's line of sight that is the part
// of each across it, in quadrature. A read is as wide across the ray as along
// it, so its width stops at ${READ_TEXELS} texels.
vec3 glowLight(vec3 p, float cut, vec3 model, vec3 d, float texel, float ds) {
	float w = catalogueWeight(p);
	vec3 j = model;
	if (w > 0.0) {
		float r2 = max(dot(p, p), 1e-18);
		float on = dot(d, p);
		float wide2 = (ds * ds * max(r2 - on * on, 0.0) + texel * texel * on * on) / r2;
		j += w * light(p, cut, clamp(wide2, texel * texel, ${(READ_TEXELS ** 2).toFixed(1)} * texel * texel));
	}
	return j;
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
	vec3 d = rayDirection();
	float jitter = rayJitter();
	float pixel = pixelAngle(d);
	vec2 span = glowSpan(uOrigin, d);
	float near = span.x;
	float far = span.y;
	bool hit = far > near;
	vec3 sum = vec3(0.0);
	float column = 0.0;
	vec3 seen = vec3(1.0);
	if (hit) {
		float scale = dustSliceScale(near);
		float lnq = dustSliceSpan(near, far) / ${steps.toFixed(1)};
		float q = exp(lnq);
		// e is s + scale, so ds = e * lnq for each step of the log.
		float e = scale * exp(jitter * lnq);
		for (int i = 0; i < ${steps}; i++) {
			float s = near + e - scale;
			vec3 p = uOrigin + d * s;
			float ds = e * lnq;
			${step.density}
			float cut = uCut - ${MODULUS_LN} * log(max(s, 1e-3) / 10.0) - ${K_G.toFixed(3)} * (column + 0.5 * rise);
			vec3 depth = rise * vec3(${K_RGB.map((k) => glslFloat(MAG_LN * k)).join(', ')});
			vec3 through = exp(-depth);
			// The mean of the light through the step. A thin step needs the series.
			vec3 mean = rise > 0.01 ? (1.0 - through) / depth : 1.0 - 0.5 * depth;
			${step.light}
			seen *= through;
			column += rise;
			e *= q;
		}
	}
	${marched.stars ? outerSpanGlsl(clouds.length) : ''}
	${cloud.march}
	outLight = vec4(sum * ${glslFloat(AT_TEN_PC / meta.texture_scale)}, 0.0);
}
`;
}

/** One program of the march and its uniforms. */
class MarchProgram {
	readonly pass: FullscreenPass;
	readonly uOrigin: WebGLUniformLocation | null;
	readonly uCut: WebGLUniformLocation | null;
	readonly uJitter: WebGLUniformLocation | null;
	readonly uRayAxes: WebGLUniformLocation | null;
	readonly uLens: WebGLUniformLocation | null;
	readonly uTexel: WebGLUniformLocation | null;
	readonly uSubTexel: WebGLUniformLocation | null;
	readonly uCoarseOn: WebGLUniformLocation | null;

	constructor(
		renderer: WebGLRenderer,
		fragment: string,
		samplers: string[],
		meta: GlowMetadata,
		coarse: Float32Array | null
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		this.pass = new FullscreenPass(renderer, fragment);
		this.uOrigin = this.pass.uniform('uOrigin');
		this.uCut = this.pass.uniform('uCut');
		this.uJitter = this.pass.uniform('uJitter');
		this.uRayAxes = this.pass.uniform('uRayAxes');
		this.uLens = this.pass.uniform('uLens');
		this.uTexel = this.pass.uniform('uTexel');
		this.uSubTexel = this.pass.uniform('uSubTexel');
		this.uCoarseOn = coarse ? this.pass.uniform('uCoarseOn') : null;
		this.pass.samplers(samplers);
		gl.uniform4fv(this.pass.uniform('uCurve'), glowCurve(meta));
		if (meta.model) gl.uniform3fv(this.pass.uniform('uModelColour'), modelColours(meta.model));
		if (coarse) gl.uniform4fv(this.pass.uniform('uCoarse'), coarse);
	}
}

/** What the march reads of the emission: its block, its textures and the parts
 *  that draw. */
export interface MarchEmission {
	meta: GlowEmission;
	textures: EmissionTextures;
	parts: EmissionParts;
}

/** The camera's rays for the screen target: view to nest axes, as the columns of
 *  a GLSL mat3, the lens as the composite has it, and where in its texel this
 *  pass's ray goes (`subTexel`). */
export interface MarchView {
	axes: Float32List;
	lens: readonly [number, number, number, number];
	offset: readonly [number, number];
}

/**
 * Where in its texel a pass's ray goes, from the centre, in texels. Pass 0 is
 * at the centre, so a view in motion does not shift. The others are on a ring
 * at even angles, so all passes together have their mean at the centre and the
 * spread of a box one texel wide: the picture at rest is anti-aliased.
 */
export function subTexel(pass: number, passes: number, out: [number, number]): [number, number] {
	const ring = passes - 1;
	if (pass === 0 || ring < 2) {
		out[0] = out[1] = 0;
		return out;
	}
	const radius = Math.sqrt(passes / (6 * ring));
	const angle = (2 * Math.PI * (pass - 1)) / ring;
	out[0] = radius * Math.cos(angle);
	out[1] = radius * Math.sin(angle);
	return out;
}

export class GlowMarch {
	private readonly screen: MarchProgram;
	/** The emission alone, for the sky map at the Sun inside the solar system. */
	private readonly alone: MarchProgram | null;
	private readonly textures: { target: number; texture: WebGLTexture }[];
	/** Debug: off, every sample reads the grid itself. */
	coarseReads = true;

	constructor(
		private readonly renderer: WebGLRenderer,
		nest: NestTextures,
		grid: VolumeTextures,
		model: VolumeTextures | null,
		far: { textures: VolumeTextures; entry: FarDustEntry } | null,
		meta: GlowMetadata,
		entry: GlowTierEntry,
		steps: { screen: number; sky: number },
		sunSize: number,
		tier: GlowGridTier,
		emission: MarchEmission | null = null,
		clouds: readonly CloudBox[] = [],
		coarse: CoarseLayout | null = null
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const parts = emission?.parts ?? NO_PARTS;
		const samplers = [
			...nest.levels.map((_, i) => `uLevel${i}`),
			'uA',
			'uB',
			...(coarse ? ['uCoarseA', 'uCoarseB'] : []),
			...(model ? ['uModelInner', 'uModelOuter'] : []),
			...(far ? ['uFar'] : []),
			...emissionSamplers(parts)
		];
		const volume = (texture: WebGLTexture) => ({ target: gl.TEXTURE_3D, texture });
		this.textures = [
			...nest.textures.map(volume),
			...grid.textures.map(volume),
			...(model?.textures ?? []).map(volume),
			...(far?.textures.textures ?? []).map(volume),
			...(emission ? emission.textures.bindings(parts, gl) : [])
		];
		const boxes = coarse && coarseUniforms(coarse, entry.size);
		const made: MarchProgram[] = [];
		const program = (kind: MapKind, size: number, stars: boolean) => {
			const light = { stars, parts, emission: emission?.meta ?? null };
			const fragment = fragmentShader(
				nest,
				meta,
				entry,
				kind === 'screen' ? steps.screen : steps.sky,
				kind,
				size,
				far?.entry ?? null,
				light,
				tier,
				clouds,
				coarse
			);
			const marched = new MarchProgram(renderer, fragment, samplers, meta, boxes);
			made.push(marched);
			return marched;
		};
		try {
			this.screen = program('screen', 0, true);
			this.alone = parts.halpha || parts.scatter ? program('sky', sunSize, false) : null;
		} catch (err) {
			for (const p of made) p.pass.dispose();
			throw err;
		}
	}

	/** The emission alone draws: a sky map at the Sun of it is of use. */
	get emissionAlone(): boolean {
		return this.alone !== null;
	}

	/**
	 * March a whole target from `origin`. The first pass writes; a later one
	 * blends in with `weight`, so the target stays the mean of its passes. With
	 * a `view`, the target is the screen's; without, it is the octahedral map of
	 * the emission alone.
	 */
	run(
		target: PassTarget,
		origin: Vec3,
		cut: number,
		jitter: number,
		weight: number,
		view: MarchView | null
	): void {
		const program = view ? this.screen : this.alone;
		if (!program) return;
		program.pass.run(
			target,
			(gl) => {
				const { state } = this.renderer;
				this.textures.forEach(({ target: kind, texture }, i) => {
					state.bindTexture(kind, texture, gl.TEXTURE0 + i);
				});
				gl.uniform3f(program.uOrigin, origin[0], origin[1], origin[2]);
				gl.uniform1f(program.uCut, cut);
				gl.uniform1f(program.uJitter, jitter);
				if (program.uCoarseOn) gl.uniform1i(program.uCoarseOn, this.coarseReads ? 1 : 0);
				if (view) {
					gl.uniformMatrix3fv(program.uRayAxes, false, view.axes);
					gl.uniform4f(program.uLens, ...view.lens);
					gl.uniform2f(program.uTexel, 1 / target.width, 1 / target.height);
					gl.uniform2f(program.uSubTexel, view.offset[0], view.offset[1]);
				}
			},
			weight
		);
	}

	dispose(): void {
		this.screen.pass.dispose();
		this.alone?.pass.dispose();
	}
}
