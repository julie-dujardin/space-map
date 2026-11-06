/**
 * The march that fills a sky map. It holds the nest as 3D textures and draws
 * into the layers of a 2D array, which three's render targets cannot do.
 *
 * The GL calls go through `renderer.state`, so three's cache stays true.
 * Do not call `renderer.resetState()` after this: it turns reversed-Z off.
 */

import {
	AddEquation,
	Color,
	ConstantAlphaFactor,
	CustomBlending,
	ExternalTexture,
	NoBlending,
	OneMinusConstantAlphaFactor,
	Vector4,
	type WebGLRenderer
} from 'three';
import {
	DUST_MAP_LAYERS,
	DUST_MAP_SIZE,
	DUST_MAP_SLICES,
	DUST_RAY_GLSL,
	DUST_SLICE_STEPS
} from './layout';
import type { NestLevel } from './nest';
import { OCT_DIRECTION_GLSL, type Vec3 } from './octahedral';
import { glslFloat, glslVec3 } from './glsl';

/** What the march needs to know of a level. The codes stay out of it, so the
 *  `high` nest leaves the heap after the upload. */
export type LevelShape = Omit<NestLevel, 'codes'>;

/** Bytes of a level that go to the GPU in one frame. */
const UPLOAD_BYTES_PER_FRAME = 4 * 1024 * 1024;

const VERTEX = /* glsl */ `#version 300 es
void main() {
	vec2 at = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
	gl_Position = vec4(at * 2.0 - 1.0, 0.0, 1.0);
}
`;

/** One branch for each level, fine to coarse. A sample reads the finest level
 *  that holds it. */
export function densityGlsl(levels: readonly LevelShape[]): string {
	const branches = levels.map((level, i) => {
		const read = `uLevel${i}`;
		const half = glslVec3(level.half);
		const decode = `${glslFloat(level.floor)} * (exp(textureLod(${read}, (p + ${half}) / (2.0 * ${half}), 0.0).r * ${glslFloat(level.span)}) - 1.0)`;
		return `if (all(lessThanEqual(a, ${half}))) return ${decode};`;
	});
	return /* glsl */ `
highp float density(highp vec3 p) {
	highp vec3 a = abs(p);
	${branches.reverse().join('\n\t')}
	return 0.0;
}
`;
}

function fragmentShader(levels: readonly LevelShape[]): string {
	const steps = DUST_MAP_SLICES * DUST_SLICE_STEPS;
	const outputs = Array.from(
		{ length: DUST_MAP_LAYERS },
		(_, i) => `layout(location = ${i}) out highp vec4 out${i};`
	);
	const writes = Array.from({ length: DUST_MAP_LAYERS }, (_, i) => {
		const at = 3 * i;
		return `out${i} = vec4(a[${at}], a[${at + 1}], a[${at + 2}], a[${at + 3}]);`;
	});
	return /* glsl */ `#version 300 es
precision highp float;
precision highp sampler3D;
${levels.map((_, i) => `uniform sampler3D uLevel${i};`).join('\n')}
uniform vec3 uOrigin;
uniform float uJitter;
${outputs.join('\n')}
${OCT_DIRECTION_GLSL}
${DUST_RAY_GLSL}
${densityGlsl(levels)}
void main() {
	vec3 d = dustOctDirection(gl_FragCoord.xy / ${DUST_MAP_SIZE.toFixed(1)});
	vec2 span = dustBoxSpan(uOrigin, d);
	float near = span.x;
	float far = span.y;
	float a[${DUST_MAP_SLICES + 1}];
	for (int i = 0; i <= ${DUST_MAP_SLICES}; i++) a[i] = 0.0;
	if (far > near) {
		float scale = dustSliceScale(near);
		float lnq = dustSliceSpan(near, far) / ${steps.toFixed(1)};
		float q = exp(lnq);
		// e is s + scale, so ds = e * lnq for each step of the log.
		float e = scale * exp(uJitter * lnq);
		float sum = 0.0;
		for (int i = 0; i < ${DUST_MAP_SLICES}; i++) {
			for (int j = 0; j < ${DUST_SLICE_STEPS}; j++) {
				sum += density(uOrigin + d * (near + e - scale)) * e * lnq;
				e *= q;
			}
			a[i + 1] = sum;
		}
	}
	${writes.join('\n\t')}
}
`;
}

function compile(gl: WebGL2RenderingContext, kind: number, source: string): WebGLShader {
	const shader = gl.createShader(kind);
	if (!shader) throw new Error('dust: no shader');
	gl.shaderSource(shader, source);
	gl.compileShader(shader);
	return shader;
}

function link(gl: WebGL2RenderingContext, vertex: string, fragment: string): WebGLProgram {
	const program = gl.createProgram();
	const vs = compile(gl, gl.VERTEX_SHADER, vertex);
	const fs = compile(gl, gl.FRAGMENT_SHADER, fragment);
	gl.attachShader(program, vs);
	gl.attachShader(program, fs);
	gl.linkProgram(program);
	const linked = gl.getProgramParameter(program, gl.LINK_STATUS) as boolean;
	const log = linked
		? ''
		: `${gl.getProgramInfoLog(program)} ${gl.getShaderInfoLog(fs)} ${gl.getShaderInfoLog(vs)}`;
	gl.deleteShader(vs);
	gl.deleteShader(fs);
	if (!linked) {
		gl.deleteProgram(program);
		throw new Error(`dust march: ${log}`);
	}
	return program;
}

/** A square target of a full-screen pass. */
export interface PassTarget {
	readonly framebuffer: WebGLFramebuffer;
	readonly size: number;
}

/**
 * A program that draws one triangle over a square target. It leaves depth test
 * and mask on: three keeps them on between renders, or its next clear leaves
 * depth.
 */
export class FullscreenPass {
	private readonly program: WebGLProgram;
	private readonly vao: WebGLVertexArrayObject;

	constructor(
		private readonly renderer: WebGLRenderer,
		fragment: string
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		this.program = link(gl, VERTEX, fragment);
		this.vao = gl.createVertexArray();
	}

	uniform(name: string): WebGLUniformLocation | null {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		return gl.getUniformLocation(this.program, name);
	}

	/** Give the samplers texture units 0, 1, … in order. The program stays in
	 *  use, so uniforms that never change can follow. */
	samplers(names: readonly string[]): void {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		this.renderer.state.useProgram(this.program);
		names.forEach((name, i) => gl.uniform1i(gl.getUniformLocation(this.program, name), i));
	}

	/**
	 * Draw into `target`, with `bind` for this draw's textures and uniforms. A
	 * `weight` under 1 blends the draw in, so the target keeps the mean of its
	 * passes. `rows` limits it to `count` rows from `from`.
	 */
	run(
		target: PassTarget,
		bind: (gl: WebGL2RenderingContext) => void,
		weight = 1,
		rows?: { from: number; count: number }
	): void {
		const { renderer, program, vao } = this;
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const { state } = renderer;
		const vaoBefore = gl.getParameter(gl.VERTEX_ARRAY_BINDING) as WebGLVertexArrayObject | null;
		state.bindFramebuffer(gl.FRAMEBUFFER, target.framebuffer);
		state.viewport(rect.set(0, 0, target.size, target.size));
		if (rows) state.scissor(rect.set(0, rows.from, target.size, rows.count));
		state.setScissorTest(rows !== undefined);
		state.buffers.depth.setTest(false);
		state.buffers.depth.setMask(false);
		state.buffers.stencil.setTest(false);
		state.buffers.color.setMask(true);
		state.disable(gl.CULL_FACE);
		state.setPolygonOffset(false);
		state.disable(gl.SAMPLE_ALPHA_TO_COVERAGE);
		if (weight >= 1) state.setBlending(NoBlending);
		else {
			// The types of three leave out the last two arguments, the blend colour.
			(state.setBlending as (...args: unknown[]) => void)(
				CustomBlending,
				AddEquation,
				ConstantAlphaFactor,
				OneMinusConstantAlphaFactor,
				AddEquation,
				ConstantAlphaFactor,
				OneMinusConstantAlphaFactor,
				blendColor,
				weight
			);
		}
		state.useProgram(program);
		bind(gl);
		gl.bindVertexArray(vao);
		gl.drawArrays(gl.TRIANGLES, 0, 3);
		gl.bindVertexArray(vaoBefore);
		renderer.setRenderTarget(renderer.getRenderTarget());
		state.setBlending(NoBlending);
		state.buffers.depth.setTest(true);
		state.buffers.depth.setMask(true);
	}

	dispose(): void {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		gl.deleteProgram(this.program);
		gl.deleteVertexArray(this.vao);
	}
}

/**
 * An RGBA16F square that three can sample, with the framebuffer that draws into
 * it. With `layers`, it is a 2D array with a draw buffer for each layer.
 */
export class SkyMap implements PassTarget {
	readonly texture: WebGLTexture;
	readonly framebuffer: WebGLFramebuffer;
	readonly external: ExternalTexture;

	constructor(
		private readonly renderer: WebGLRenderer,
		readonly size: number,
		layers = 0
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const { state } = renderer;
		const target = layers > 0 ? gl.TEXTURE_2D_ARRAY : gl.TEXTURE_2D;
		this.texture = gl.createTexture();
		state.bindTexture(target, this.texture);
		if (layers > 0) gl.texStorage3D(target, 1, gl.RGBA16F, size, size, layers);
		else gl.texStorage2D(target, 1, gl.RGBA16F, size, size);
		gl.texParameteri(target, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
		gl.texParameteri(target, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
		gl.texParameteri(target, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(target, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
		this.framebuffer = gl.createFramebuffer();
		state.bindFramebuffer(gl.FRAMEBUFFER, this.framebuffer);
		if (layers > 0) {
			const buffers: number[] = [];
			for (let i = 0; i < layers; i++) {
				gl.framebufferTextureLayer(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0 + i, this.texture, 0, i);
				buffers.push(gl.COLOR_ATTACHMENT0 + i);
			}
			gl.drawBuffers(buffers);
		} else {
			gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, target, this.texture, 0);
		}
		const status = gl.checkFramebufferStatus(gl.FRAMEBUFFER);
		state.bindFramebuffer(gl.FRAMEBUFFER, null);
		renderer.setRenderTarget(renderer.getRenderTarget());
		if (status !== gl.FRAMEBUFFER_COMPLETE) {
			// The caller has no object to dispose, so the half-made map goes here.
			gl.deleteFramebuffer(this.framebuffer);
			gl.deleteTexture(this.texture);
			throw new Error(`sky map: framebuffer ${status}`);
		}
		this.external = new ExternalTexture(this.texture);
	}

	dispose(): void {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		gl.deleteFramebuffer(this.framebuffer);
		gl.deleteTexture(this.texture);
		this.external.dispose();
	}
}

/** Whether this context can draw into a sky map. */
export function canMarch(renderer: WebGLRenderer): boolean {
	const gl = renderer.getContext() as WebGL2RenderingContext;
	return (
		gl.getExtension('EXT_color_buffer_float') !== null &&
		(gl.getParameter(gl.MAX_DRAW_BUFFERS) as number) >= DUST_MAP_LAYERS
	);
}

/** A volume for the GPU: its size in texels, and its texels row by row. */
export interface Volume {
	size: Vec3;
	data: Uint8Array | Uint16Array;
}

/** One byte a texel, one half float, or four. */
export type VolumeFormat = 'r8' | 'r16f' | 'rgba16f';

/** GL formats of a volume, and its values a texel. */
function volumeFormat(gl: WebGL2RenderingContext, format: VolumeFormat) {
	if (format === 'r8')
		return { internal: gl.R8, layout: gl.RED, type: gl.UNSIGNED_BYTE, channels: 1 };
	if (format === 'r16f')
		return { internal: gl.R16F, layout: gl.RED, type: gl.HALF_FLOAT, channels: 1 };
	return { internal: gl.RGBA16F, layout: gl.RGBA, type: gl.HALF_FLOAT, channels: 4 };
}

/** 3D textures that upload a few slices each frame. */
export class VolumeTextures {
	readonly textures: WebGLTexture[];
	private uploads: { volume: Volume; texture: WebGLTexture; next: number }[];

	constructor(
		private readonly renderer: WebGLRenderer,
		volumes: readonly Volume[],
		private readonly format: VolumeFormat
	) {
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const { internal } = volumeFormat(gl, format);
		this.textures = volumes.map(({ size }) => {
			const texture = gl.createTexture();
			renderer.state.bindTexture(gl.TEXTURE_3D, texture);
			gl.texStorage3D(gl.TEXTURE_3D, 1, internal, size[0], size[1], size[2]);
			// No mipmaps: the filter must stay on the voxels.
			gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
			gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
			gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
			gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
			gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
			return texture;
		});
		this.uploads = volumes.map((volume, i) => ({ volume, texture: this.textures[i], next: 0 }));
	}

	get uploaded(): boolean {
		return this.uploads.length === 0;
	}

	/** Upload the next slices. */
	step(): void {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		const { state } = this.renderer;
		const { layout, type, channels } = volumeFormat(gl, this.format);
		gl.pixelStorei(gl.UNPACK_ALIGNMENT, this.format === 'r8' ? 1 : 2);
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
		let bytes = UPLOAD_BYTES_PER_FRAME;
		while (bytes > 0 && this.uploads.length > 0) {
			const upload = this.uploads[0];
			const { size, data } = upload.volume;
			const [nx, ny, nz] = size;
			const plane = nx * ny * channels;
			const planeBytes = plane * data.BYTES_PER_ELEMENT;
			const count = Math.min(Math.max(Math.floor(bytes / planeBytes), 1), nz - upload.next);
			state.bindTexture(gl.TEXTURE_3D, upload.texture);
			gl.texSubImage3D(
				gl.TEXTURE_3D,
				0,
				0,
				0,
				upload.next,
				nx,
				ny,
				count,
				layout,
				type,
				data,
				plane * upload.next
			);
			upload.next += count;
			bytes -= count * planeBytes;
			if (upload.next === nz) this.uploads.shift();
		}
		gl.pixelStorei(gl.UNPACK_ALIGNMENT, 4);
	}

	dispose(): void {
		const gl = this.renderer.getContext() as WebGL2RenderingContext;
		for (const texture of this.textures) gl.deleteTexture(texture);
		this.uploads = [];
	}
}

/** The nest on the GPU, one R8 texture a level. */
export class NestTextures extends VolumeTextures {
	readonly levels: readonly LevelShape[];

	constructor(renderer: WebGLRenderer, levels: readonly NestLevel[]) {
		super(
			renderer,
			levels.map(({ size, codes }) => ({ size, data: codes })),
			'r8'
		);
		this.levels = levels.map(({ half, floor, span, size }) => ({ half, floor, span, size }));
	}
}

export class DustMarch {
	private readonly pass: FullscreenPass;
	private readonly uOrigin: WebGLUniformLocation | null;
	private readonly uJitter: WebGLUniformLocation | null;

	constructor(
		private readonly renderer: WebGLRenderer,
		private readonly nest: NestTextures
	) {
		this.pass = new FullscreenPass(renderer, fragmentShader(nest.levels));
		this.uOrigin = this.pass.uniform('uOrigin');
		this.uJitter = this.pass.uniform('uJitter');
		this.pass.samplers(nest.levels.map((_, i) => `uLevel${i}`));
	}

	/**
	 * One pass over a map. The first pass writes; a later one blends in with
	 * `weight`, so the map stays the mean of its passes.
	 */
	run(map: SkyMap, origin: Vec3, jitter: number, weight: number): void {
		this.pass.run(
			map,
			(gl) => {
				this.nest.textures.forEach((texture, i) => {
					this.renderer.state.bindTexture(gl.TEXTURE_3D, texture, gl.TEXTURE0 + i);
				});
				gl.uniform3f(this.uOrigin, origin[0], origin[1], origin[2]);
				gl.uniform1f(this.uJitter, jitter);
			},
			weight
		);
	}

	dispose(): void {
		this.pass.dispose();
	}
}

const rect = new Vector4();
const blendColor = new Color(0, 0, 0);
