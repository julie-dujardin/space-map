/**
 * The glow's exposure, kept on the GPU (`exposure.ts` has the law). Two passes
 * sum a finished map to its mean brightness over the sphere, each texel weighted
 * by the solid angle it covers. While the eye adapts, a pass on one texel each
 * frame eases the gain toward what the means ask for, and the composite reads
 * it there. No value comes back to the CPU, because a read of a float target
 * stalls a weak GPU for a whole frame. Only an occlusion query says when the
 * eye is close to its target, a few frames late, so the frame loop can stop.
 * Another says whether the model holds a visible share of a map's light, for
 * the label that says so.
 *
 * It draws through the `FullscreenPass` of the dust march.
 */

import { ExternalTexture, type WebGLRenderer } from 'three';
import { FullscreenPass, type PassTarget, type SkyMap } from '$lib/scene/dust/march';
import { octDirectionGlsl } from '$lib/scene/dust/octahedral';
import { ADAPT_CLOSE, ADAPT_POWER, MAX_GAIN, MIN_GAIN, eyeKeep } from './exposure';
import { glslFloat } from '$lib/scene/dust/glsl';

/** Edge of the first pass's target: each of its texels sums a block of the map. */
const BLOCKS = 16;
const LUMA = 'vec3(0.2126, 0.7152, 0.0722)';

/** Weighted mean of each block of the square of the map, past its ring of one
 *  texel: the luma in r, the model's luma (the map's alpha) in b. */
function blockShader(size: number): string {
	const inner = size - 2;
	const most = Math.ceil(inner / BLOCKS);
	return /* glsl */ `#version 300 es
precision highp float;
precision highp sampler2D;
uniform sampler2D uMap;
layout(location = 0) out highp vec4 outMean;
${octDirectionGlsl(size)}

void main() {
	ivec2 block = ivec2(gl_FragCoord.xy);
	ivec2 from = 1 + (block * ${inner}) / ${BLOCKS};
	ivec2 to = 1 + ((block + 1) * ${inner}) / ${BLOCKS};
	float sum = 0.0;
	float model = 0.0;
	float weight = 0.0;
	for (int j = 0; j < ${most}; j++) {
		for (int i = 0; i < ${most}; i++) {
			ivec2 at = from + ivec2(i, j);
			if (at.x < to.x && at.y < to.y) {
				vec3 d = abs(dustOctDirection((vec2(at) + 0.5) / ${size.toFixed(1)}));
				// A texel's solid angle goes as the cube of the L1 norm of its unit direction.
				float w = pow(d.x + d.y + d.z, 3.0);
				vec4 texel = texelFetch(uMap, at, 0);
				sum += dot(texel.rgb, ${LUMA}) * w;
				model += texel.a * w;
				weight += w;
			}
		}
	}
	outMean = vec4(sum / weight, weight, model / weight, 1.0);
}
`;
}

const TOTAL_SHADER = /* glsl */ `#version 300 es
precision highp float;
precision highp sampler2D;
uniform sampler2D uBlocks;
layout(location = 0) out highp vec4 outMean;

void main() {
	float sum = 0.0;
	float model = 0.0;
	float weight = 0.0;
	for (int j = 0; j < ${BLOCKS}; j++) {
		for (int i = 0; i < ${BLOCKS}; i++) {
			vec3 block = texelFetch(uBlocks, ivec2(i, j), 0).rgb;
			sum += block.r * block.g;
			model += block.b * block.g;
			weight += block.g;
		}
	}
	outMean = vec4(sum / weight, 0.0, model / weight, 1.0);
}
`;

/** Two stages in log gain, so a change starts and ends without a step in value
 *  or in speed. r and g are the stages, b the target. */
const EYE_SHADER = /* glsl */ `#version 300 es
precision highp float;
precision highp sampler2D;
uniform sampler2D uSun;
uniform sampler2D uFront;
uniform sampler2D uState;
uniform float uKeep;
layout(location = 0) out highp vec4 outState;

void main() {
	float sun = texelFetch(uSun, ivec2(0), 0).r;
	float mean = texelFetch(uFront, ivec2(0), 0).r;
	float goal = 0.0;
	if (sun > 0.0 && mean > 0.0) {
		goal = clamp(${glslFloat(ADAPT_POWER)} * log(sun / mean), ${glslFloat(Math.log(MIN_GAIN))}, ${glslFloat(Math.log(MAX_GAIN))});
	}
	vec2 was = texelFetch(uState, ivec2(0), 0).rg;
	float first = goal + (was.x - goal) * uKeep;
	float second = first + (was.y - first) * uKeep;
	outState = vec4(first, second, goal, 1.0);
}
`;

/** Draws one fragment while either stage of the eye is not yet close to its target. */
const CLOSE_SHADER = /* glsl */ `#version 300 es
precision highp float;
precision highp sampler2D;
uniform sampler2D uState;
layout(location = 0) out highp vec4 outFar;

void main() {
	vec3 state = texelFetch(uState, ivec2(0), 0).rgb;
	float close = ${glslFloat(Math.log1p(ADAPT_CLOSE))};
	if (abs(state.r - state.b) < close && abs(state.g - state.b) < close) discard;
	outFar = vec4(1.0);
}
`;

/** Draws one fragment where the model holds at least `uShare` of the front map's light. */
const SHARE_SHADER = /* glsl */ `#version 300 es
precision highp float;
precision highp sampler2D;
uniform sampler2D uFront;
uniform float uShare;
layout(location = 0) out highp vec4 outShown;

void main() {
	vec4 mean = texelFetch(uFront, ivec2(0), 0);
	if (!(mean.b >= uShare * mean.r) || mean.r <= 0.0) discard;
	outShown = vec4(1.0);
}
`;

/** An occlusion query that the frame loop polls and never waits on. */
class Question {
	readonly query: WebGLQuery;
	/** A question is out. */
	asking = false;
	/** What it asked about changed after it went out, so its answer is of no use. */
	moot = false;
	/** The pass of the last ask. */
	private draw: (() => void) | null = null;

	constructor(private readonly gl: WebGL2RenderingContext) {
		this.query = gl.createQuery();
	}

	/** Ask with `draw`, whose fragments are the answer, unless a question is out. */
	ask(draw: () => void): void {
		this.draw = draw;
		if (!this.asking) this.send(draw);
	}

	private send(draw: () => void): void {
		this.asking = true;
		this.moot = false;
		const { gl } = this;
		// Only the pass's one fragment draws between begin and end.
		gl.beginQuery(gl.ANY_SAMPLES_PASSED, this.query);
		draw();
		gl.endQuery(gl.ANY_SAMPLES_PASSED);
	}

	/** Whether the pass drew. Null while the answer is not in, or with no
	 *  question out, or when the question went moot. With `again`, a moot answer
	 *  sends the last ask, so it is of what is there now. */
	answer(again = false): boolean | null {
		if (!this.asking) return null;
		const { gl } = this;
		// A lost context gives no answer. The restore builds a new eye.
		if (gl.isContextLost()) {
			this.asking = false;
			return null;
		}
		if (!gl.getQueryParameter(this.query, gl.QUERY_RESULT_AVAILABLE)) return null;
		this.asking = false;
		const drew = (gl.getQueryParameter(this.query, gl.QUERY_RESULT) as number) > 0;
		if (!this.moot) return drew;
		if (again && this.draw) this.send(this.draw);
		return null;
	}

	dispose(): void {
		this.gl.deleteQuery(this.query);
	}
}

/** A 1 × 1 or small float target. */
interface Target extends PassTarget {
	texture: WebGLTexture;
}

export class GlowEye {
	private readonly blocks: Target;
	/** One texel of the blocks, which are scratch between two measures. */
	private readonly scratch: PassTarget;
	private readonly sun: Target;
	private readonly front: Target;
	private readonly states: [Target, Target];
	/** What three samples: each state's texture. */
	private readonly externals: [ExternalTexture, ExternalTexture];
	private current = 0;
	private readonly blockPass: FullscreenPass;
	private readonly totalPass: FullscreenPass;
	private readonly eyePass: FullscreenPass;
	private readonly closePass: FullscreenPass;
	private readonly sharePass: FullscreenPass;
	private readonly uKeep: WebGLUniformLocation | null;
	private readonly uShare: WebGLUniformLocation | null;
	private readonly close: Question;
	private readonly share: Question;

	constructor(
		private readonly renderer: WebGLRenderer,
		size: number
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const made: Target[] = [];
		const make = (edge: number, format: number) => {
			const target = this.target(edge, format);
			made.push(target);
			return target;
		};
		try {
			this.blocks = make(BLOCKS, gl.RGBA16F);
			// Thirty-two bits: a frame's step of the eye is under the precision of a half.
			this.sun = make(1, gl.RGBA32F);
			this.front = make(1, gl.RGBA32F);
			this.states = [make(1, gl.RGBA32F), make(1, gl.RGBA32F)];
		} catch (err) {
			for (const target of made) this.free(target);
			throw err;
		}
		this.scratch = { framebuffer: this.blocks.framebuffer, size: 1 };
		this.externals = [
			new ExternalTexture(this.states[0].texture),
			new ExternalTexture(this.states[1].texture)
		];
		this.blockPass = new FullscreenPass(renderer, blockShader(size));
		this.totalPass = new FullscreenPass(renderer, TOTAL_SHADER);
		this.eyePass = new FullscreenPass(renderer, EYE_SHADER);
		this.closePass = new FullscreenPass(renderer, CLOSE_SHADER);
		this.sharePass = new FullscreenPass(renderer, SHARE_SHADER);
		this.close = new Question(gl);
		this.share = new Question(gl);
		this.blockPass.samplers(['uMap']);
		this.totalPass.samplers(['uBlocks']);
		this.eyePass.samplers(['uSun', 'uFront', 'uState']);
		this.uKeep = this.eyePass.uniform('uKeep');
		this.closePass.samplers(['uState']);
		this.sharePass.samplers(['uFront']);
		this.uShare = this.sharePass.uniform('uShare');
	}

	private target(edge: number, format: number): Target {
		const { renderer } = this;
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const texture = gl.createTexture();
		renderer.state.bindTexture(gl.TEXTURE_2D, texture);
		gl.texStorage2D(gl.TEXTURE_2D, 1, format, edge, edge);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
		const framebuffer = gl.createFramebuffer();
		renderer.state.bindFramebuffer(gl.FRAMEBUFFER, framebuffer);
		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
		const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
		renderer.state.bindFramebuffer(gl.FRAMEBUFFER, null);
		renderer.setRenderTarget(renderer.getRenderTarget());
		const target = { texture, framebuffer, size: edge };
		if (status !== gl.FRAMEBUFFER_COMPLETE) {
			this.free(target);
			throw new Error(`glow: eye framebuffer ${status}`);
		}
		return target;
	}

	/** The gain over the Sun's exposure, as a texture: log gain in g. */
	get texture(): ExternalTexture {
		return this.externals[this.current];
	}

	/** Bind a 2D texture to a unit. */
	private bind(gl: WebGL2RenderingContext, texture: WebGLTexture, unit: number): void {
		this.renderer.state.bindTexture(gl.TEXTURE_2D, texture, gl.TEXTURE0 + unit);
	}

	/** Sum a finished map: the reference at the Sun, or the map that takes over. */
	measure(map: SkyMap, reference: boolean): void {
		this.close.moot = this.close.asking;
		if (!reference) this.share.moot = this.share.asking;
		this.blockPass.run(this.blocks, (gl) => this.bind(gl, map.texture, 0));
		this.totalPass.run(reference ? this.sun : this.front, (gl) =>
			this.bind(gl, this.blocks.texture, 0)
		);
	}

	/** One frame of the eye. `atOnce` takes the target with no easing. */
	step(dtMs: number, atOnce: boolean): void {
		const from = this.states[this.current];
		this.current = 1 - this.current;
		this.eyePass.run(this.states[this.current], (gl) => {
			gl.uniform1f(this.uKeep, atOnce ? 0 : eyeKeep(dtMs));
			this.bind(gl, this.sun.texture, 0);
			this.bind(gl, this.front.texture, 1);
			this.bind(gl, from.texture, 2);
		});
	}

	/** Ask the GPU whether the eye is close to its target, unless a question is out. */
	ask(): void {
		this.close.ask(() =>
			this.closePass.run(this.scratch, (gl) => this.bind(gl, this.states[this.current].texture, 0))
		);
	}

	/** True when the last question found the eye close to the target it still
	 *  has. Null while the answer is not in, or with no question out. */
	answer(): boolean | null {
		const far = this.close.answer();
		return far === null ? null : !far;
	}

	/** Ask whether the model holds at least `share` of the front map's light. */
	askShare(share: number): void {
		this.share.ask(() =>
			this.sharePass.run(this.scratch, (gl) => {
				gl.uniform1f(this.uShare, share);
				this.bind(gl, this.front.texture, 0);
			})
		);
	}

	/** The answer to `askShare`, as `answer` gives its own. A moot answer is of a
	 *  map that no longer shows, so the question goes again for the front map. */
	shareAnswer(): boolean | null {
		return this.share.answer(true);
	}

	/** A question on the model's share is out. */
	get sharePending(): boolean {
		return this.share.asking;
	}

	/** For the gates: the gain, its target and the two means. It waits for the GPU. */
	read(): { gain: number; target: number; sunMean: number; mean: number; modelMean: number } {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		const out = new Float32Array(4);
		const texel = (target: Target) => {
			this.renderer.state.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
			gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.FLOAT, out);
			return [...out];
		};
		const eye = texel(this.states[this.current]);
		const sunMean = texel(this.sun)[0];
		const [mean, , modelMean] = texel(this.front);
		this.renderer.state.bindFramebuffer(gl.FRAMEBUFFER, null);
		this.renderer.setRenderTarget(this.renderer.getRenderTarget());
		return { gain: Math.exp(eye[1]), target: Math.exp(eye[2]), sunMean, mean, modelMean };
	}

	private free(target: Target): void {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		gl.deleteFramebuffer(target.framebuffer);
		gl.deleteTexture(target.texture);
	}

	dispose(): void {
		for (const target of [this.blocks, this.sun, this.front, ...this.states]) this.free(target);
		for (const external of this.externals) external.dispose();
		this.blockPass.dispose();
		this.totalPass.dispose();
		this.eyePass.dispose();
		this.closePass.dispose();
		this.sharePass.dispose();
		this.close.dispose();
		this.share.dispose();
	}
}
