/**
 * The march that fills the glow's sky maps. A ray holds its column of dust as it
 * goes, so the cut changes along it: a star's light is in the glow where the
 * star, seen through that dust, is under the limit. Model light adds the light
 * the catalogue lacks, so the whole Galaxy draws from any place.
 *
 * A ray has two spans. The first is inside the box of the dust and of the
 * model's inner box, and its steps restart at the entry, so a view from outside
 * spends them on the disc. One
 * step's light takes the integral of the dust across the step (Hillaire 2016),
 * so brightness does not depend on step length. The second is the rest of the
 * ray out to the reach of the grid, where the halo and the Magellanic Clouds
 * are. It has no dust of its own, so it needs few steps.
 *
 * Light that is not starlight (`emission.ts`) adds in the first span, where the
 * dust is: H-alpha at the lines' own K, and starlight that dust scatters at the
 * stars'. A second program marches these alone from the Sun, for the sky inside
 * the solar system, where the skybox holds neither.
 *
 * Alpha holds the share of model light, as luma, for the label. H-alpha and
 * scattered light are models too, so they count.
 *
 * Two kinds of map: the octahedral one holds the whole sky, and the one about
 * the Galaxy holds a square of the sky about the Galactic centre, for a camera
 * far outside, where the octahedral map spends its texels on empty sky.
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
	type SkyMap,
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
import { glowDensityGlsl, type FarDustEntry } from './far-dust';
import { modelColours, modelGlsl, type GlowModel } from './model';
import type { GalaxyFrame } from './outside';
import { glslFloat, glslVec3 } from '$lib/scene/dust/glsl';

/** Flux per sr from flux per pc³ along a ray in pc: (10 pc)². */
const AT_TEN_PC = 100;
/** The distance modulus per natural log of distance: 5 / ln 10. */
const MODULUS_LN = (2 / MAG_LN).toFixed(8);
/** Steps of the span past the box. */
export const OUTER_STEPS = 16;
/** Least scale (pc) of the outer span's steps. */
const OUTER_SCALE_PC = 100;
const LUMA = 'vec3(0.2126, 0.7152, 0.0722)';

/** Which map a program fills. */
export type MapKind = 'sky' | 'galaxy';

/** What a program marches: everything, or the emission alone. */
interface MarchLight {
	stars: boolean;
	parts: EmissionParts;
	emission: GlowEmission | null;
}

function directionGlsl(kind: MapKind, size: number): string {
	if (kind === 'sky') {
		return `${octDirectionGlsl(size)}
vec3 rayDirection() { return dustOctDirection(gl_FragCoord.xy / ${size.toFixed(1)}); }`;
	}
	return /* glsl */ `
uniform highp mat3 uFrame;
uniform float uTan;
vec3 rayDirection() {
	vec2 q = gl_FragCoord.xy * ${glslFloat(2 / size)} - 1.0;
	return normalize(uFrame * vec3(q * uTan, 1.0));
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
function outerSpanGlsl(): string {
	return /* glsl */ `
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
			vec3 p = uOrigin + d * s;
			float cut = uCut - ${MODULUS_LN} * log(max(s, 1e-3) / 10.0) - ${K_G.toFixed(3)} * (behind ? column : 0.0);
			vec3 model = modelLight(p);
			vec3 gain = (behind ? seen : vec3(1.0)) * e * lnq;
			sum += glowLight(p, cut, model) * gain;
			modelSum += dot(model * gain, ${LUMA});
			e *= q;
		}
	}
`;
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
	const lines = parts.halpha
		? `
			vec3 lines = lineLight(p, column, rise, ds);
			sum += lines;
			modelSum += dot(lines, ${LUMA});`
		: '';
	return {
		density,
		light: `vec3 model = ${model};
			vec3 gain = seen * mean * ds;
			${stars ? 'sum += glowLight(p, cut, model) * gain;' : 'sum += model * gain;'}
			modelSum += dot(model * gain, ${LUMA});${lines}`
	};
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
	tier: GlowGridTier
): string {
	const entries = meta.table.place_soft.length;
	const levels = nest.levels;
	const reach = entry.reach_pc;
	const table = tableAxis(meta);
	const step = stepGlsl(marched);
	const emission = marched.emission
		? emissionGlsl(marched.emission, marched.parts, tier, meta.texture_scale)
		: '';
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
${directionGlsl(kind, size)}
${DUST_RAY_GLSL}
${spanGlsl(meta.model ?? null)}
${densityGlsl(levels)}
${glowDensityGlsl(levels, far)}
${octUvGlsl(entry.size, 'gridUv')}
${modelGlsl(meta.model ?? null, meta.texture_scale)}
${emission}

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

// The catalogue's light fades out with distance from the Sun, so its two
// fetches run only where it holds some.
vec3 glowLight(vec3 p, float cut, vec3 model) {
	float w = catalogueWeight(p);
	vec3 j = model;
	if (w > 0.0) j += w * light(p, cut);
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
	vec2 span = glowSpan(uOrigin, d);
	float near = span.x;
	float far = span.y;
	bool hit = far > near;
	vec3 sum = vec3(0.0);
	float modelSum = 0.0;
	float column = 0.0;
	vec3 seen = vec3(1.0);
	if (hit) {
		float scale = dustSliceScale(near);
		float lnq = dustSliceSpan(near, far) / ${steps.toFixed(1)};
		float q = exp(lnq);
		// e is s + scale, so ds = e * lnq for each step of the log.
		float e = scale * exp(uJitter * lnq);
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
	${marched.stars ? outerSpanGlsl() : ''}
	outLight = vec4(sum, modelSum) * ${glslFloat(AT_TEN_PC / meta.texture_scale)};
}
`;
}

/** The size of the maps and of their rays. */
export interface GlowShape {
	size: number;
	steps: number;
	/** Edge of the map about the Galaxy; 0 for none. */
	galaxy: number;
}

/** One program of the march and its uniforms. */
class MarchProgram {
	readonly pass: FullscreenPass;
	readonly uOrigin: WebGLUniformLocation | null;
	readonly uCut: WebGLUniformLocation | null;
	readonly uJitter: WebGLUniformLocation | null;
	readonly uFrame: WebGLUniformLocation | null;
	readonly uTan: WebGLUniformLocation | null;

	constructor(renderer: WebGLRenderer, fragment: string, samplers: string[], meta: GlowMetadata) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		this.pass = new FullscreenPass(renderer, fragment);
		this.uOrigin = this.pass.uniform('uOrigin');
		this.uCut = this.pass.uniform('uCut');
		this.uJitter = this.pass.uniform('uJitter');
		this.uFrame = this.pass.uniform('uFrame');
		this.uTan = this.pass.uniform('uTan');
		this.pass.samplers(samplers);
		gl.uniform4fv(this.pass.uniform('uCurve'), glowCurve(meta));
		if (meta.model) gl.uniform3fv(this.pass.uniform('uModelColour'), modelColours(meta.model));
	}
}

/** What the march reads of the emission: its block, its textures and the parts
 *  that draw. */
export interface MarchEmission {
	meta: GlowEmission;
	textures: EmissionTextures;
	parts: EmissionParts;
}

export class GlowMarch {
	private readonly sky: MarchProgram;
	private readonly galaxy: MarchProgram | null;
	/** The emission alone, for the sky map at the Sun inside the solar system. */
	private readonly alone: MarchProgram | null;
	private readonly textures: { target: number; texture: WebGLTexture }[];

	constructor(
		private readonly renderer: WebGLRenderer,
		nest: NestTextures,
		grid: VolumeTextures,
		model: VolumeTextures | null,
		far: { textures: VolumeTextures; entry: FarDustEntry } | null,
		meta: GlowMetadata,
		entry: GlowTierEntry,
		shape: GlowShape,
		tier: GlowGridTier,
		emission: MarchEmission | null = null
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const parts = emission?.parts ?? NO_PARTS;
		const samplers = [
			...nest.levels.map((_, i) => `uLevel${i}`),
			'uA',
			'uB',
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
		const made: MarchProgram[] = [];
		const program = (kind: MapKind, size: number, stars: boolean) => {
			const light = { stars, parts, emission: emission?.meta ?? null };
			const fragment = fragmentShader(
				nest,
				meta,
				entry,
				shape.steps,
				kind,
				size,
				far?.entry ?? null,
				light,
				tier
			);
			const marched = new MarchProgram(renderer, fragment, samplers, meta);
			made.push(marched);
			return marched;
		};
		try {
			this.sky = program('sky', shape.size, true);
			this.galaxy = shape.galaxy > 0 ? program('galaxy', shape.galaxy, true) : null;
			this.alone = parts.halpha || parts.scatter ? program('sky', shape.size, false) : null;
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
	 * March `rows` rows of a map from `from`. The first pass writes; a later one
	 * blends in with `weight`, so the map stays the mean of its passes. A map
	 * about the Galaxy needs its `frame`. With `alone`, the map holds the
	 * emission alone.
	 */
	run(
		map: SkyMap,
		origin: Vec3,
		cut: number,
		jitter: number,
		weight: number,
		from: number,
		rows: number,
		frame: GalaxyFrame | null = null,
		alone = false
	): void {
		const program = alone ? this.alone : frame ? this.galaxy : this.sky;
		if (!program) return;
		program.pass.run(
			map,
			(gl) => {
				const { state } = this.renderer;
				this.textures.forEach(({ target, texture }, i) => {
					state.bindTexture(target, texture, gl.TEXTURE0 + i);
				});
				gl.uniform3f(program.uOrigin, origin[0], origin[1], origin[2]);
				gl.uniform1f(program.uCut, cut);
				gl.uniform1f(program.uJitter, jitter);
				if (frame) {
					gl.uniformMatrix3fv(program.uFrame, false, frame.axes);
					gl.uniform1f(program.uTan, frame.tan);
				}
			},
			weight,
			{ from, count: rows }
		);
	}

	dispose(): void {
		this.sky.pass.dispose();
		this.galaxy?.pass.dispose();
		this.alone?.pass.dispose();
	}
}
