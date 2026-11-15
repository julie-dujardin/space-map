/**
 * The sky of a chart from the tile pyramid of the star map. A paint fetches
 * the tiles under its frame, draws them with one pass of a shader, and keeps
 * nothing on the GPU. All charts share one WebGL context, made at the first
 * paint.
 */

import { tileUrl } from '$lib/fetch/data-base';
import { acquireBitmap, releaseBitmap } from '$lib/flatmap/texture-cache';
import { CAP_EDGE, MAP, NORTH, chartColumns, chartRows } from '$lib/scene/lod/tile-window';
import type { ChartFrame } from './frame';
import { CHART_GLSL, rayUniforms, type Pixels, type SkySource } from './sky';
import { planSky, planYields, type SkyPlan, type SkyPyramid } from './sky-tiles';
import { webgl2Canvas } from './webgl';

// The read starts at the bottom row of the picture, so the top of the frame is
// drawn there.
const VERTEX = /* glsl */ `#version 300 es
in vec2 aCorner;
out vec2 vUv;
void main() {
	vUv = aCorner * 0.5 + 0.5;
	gl_Position = vec4(aCorner, 0.0, 1.0);
}
`;

/** The gamma that the shader takes off with two multiplies. */
const SQUARED_TWICE = 4;

/** The shader that reads `across` by `down` taps for each pixel. A tap is
 *  decoded to light before any mix: a mix of bytes dims a star. */
function fragment(across: number, down: number, gamma: number): string {
	return /* glsl */ `#version 300 es
precision highp float;
precision highp int;
precision highp sampler2DArray;

uniform sampler2DArray uTiles;
uniform vec2 uPixel;
uniform int uChart;
uniform int uTile;
// Pixels of the level, tiles of the level, first tile of the grid, tiles of the grid.
uniform ivec2 uLevel;
uniform int uLevelColumns;
uniform ivec2 uFirst;
uniform ivec2 uGrid;
uniform float uPeak;
in vec2 vUv;
out vec4 outColor;
${CHART_GLSL}
const float PI = 3.141592653589793;

vec2 chartPixel(vec3 ray) {
	vec2 at;
	if (uChart == ${MAP}) {
		at = vec2(0.5 - atan(ray.y, ray.x) / (2.0 * PI), acos(clamp(ray.z, -1.0, 1.0)) / PI);
	} else {
		float side = uChart == ${NORTH} ? 1.0 : -1.0;
		vec2 polar = ray.xy / ((1.0 + side * ray.z) * ${CAP_EDGE.toFixed(12)});
		at = 0.5 + 0.5 * vec2(polar.x, side * polar.y);
	}
	return at * vec2(uLevel);
}

vec3 texel(ivec2 p) {
	p.y = clamp(p.y, 0, uLevel.y - 1);
	ivec2 tile = ivec2(floor(vec2(p) / float(uTile)));
	ivec2 slot = tile - uFirst;
	// The map has no east edge. See gridColumn.
	if (uChart == ${MAP}) slot.x = (slot.x + uLevelColumns) % uLevelColumns;
	ivec2 held = clamp(slot, ivec2(0), uGrid - 1);
	ivec2 inside = clamp(p - tile * uTile + (slot - held) * uTile, ivec2(0), ivec2(uTile - 1));
	vec3 coded = texelFetch(uTiles, ivec3(inside, held.y * uGrid.x + held.x), 0).rgb;
	${
		gamma === SQUARED_TWICE
			? 'vec3 squared = coded * coded;\n\treturn squared * squared;'
			: `return pow(coded, vec3(${gamma.toFixed(6)}));`
	}
}

// The mix of four tile pixels. One alone gives a faint star another light in each place.
vec3 lightAt(vec2 p) {
	vec2 q = p - 0.5;
	vec2 base = floor(q);
	vec2 f = q - base;
	ivec2 i = ivec2(base);
	vec3 north = mix(texel(i), texel(i + ivec2(1, 0)), f.x);
	vec3 south = mix(texel(i + ivec2(0, 1)), texel(i + ivec2(1, 1)), f.x);
	return mix(north, south, f.y);
}

void main() {
	vec3 mean = vec3(0.0);
	vec3 peak = vec3(0.0);
	for (int j = 0; j < ${down}; j++) {
		for (int i = 0; i < ${across}; i++) {
			vec2 offset = (vec2(float(i), float(j)) + 0.5) / vec2(${across}.0, ${down}.0) - 0.5;
			vec3 tap = lightAt(chartPixel(chartRay(vUv + offset * uPixel)));
			mean += tap;
			peak = max(peak, tap);
		}
	}
	mean /= ${across * down}.0;
	outColor = vec4(chartTone(mix(mean, peak, uPeak)), 1.0);
}
`;
}

interface Program {
	program: WebGLProgram;
	uniforms: Map<string, WebGLUniformLocation | null>;
}

/** The one WebGL context of the tile sky. */
class Painter {
	private readonly programs = new Map<string, Program>();
	private readonly corners: WebGLBuffer;

	constructor(readonly gl: WebGL2RenderingContext) {
		this.corners = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, this.corners);
		gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
	}

	private compile(type: number, source: string): WebGLShader {
		const { gl } = this;
		const shader = gl.createShader(type)!;
		gl.shaderSource(shader, source);
		gl.compileShader(shader);
		return shader;
	}

	private program(across: number, down: number, gamma: number): Program {
		const key = `${across}x${down} ${gamma}`;
		const held = this.programs.get(key);
		if (held) return held;
		const { gl } = this;
		const program = gl.createProgram();
		const shaders = [
			this.compile(gl.VERTEX_SHADER, VERTEX),
			this.compile(gl.FRAGMENT_SHADER, fragment(across, down, gamma))
		];
		for (const shader of shaders) gl.attachShader(program, shader);
		gl.bindAttribLocation(program, 0, 'aCorner');
		gl.linkProgram(program);
		for (const shader of shaders) gl.deleteShader(shader);
		if (!gl.getProgramParameter(program, gl.LINK_STATUS))
			throw new Error(`star map shader: ${gl.getProgramInfoLog(program)}`);
		const made = { program, uniforms: new Map<string, WebGLUniformLocation | null>() };
		this.programs.set(key, made);
		return made;
	}

	paint(
		pyramid: SkyPyramid,
		plan: SkyPlan,
		tiles: readonly ImageBitmap[],
		frame: ChartFrame,
		width: number,
		height: number
	): Pixels {
		const { gl } = this;
		const size = pyramid.tile_size;
		const { program, uniforms } = this.program(...plan.taps, pyramid.light_gamma);
		const at = (name: string): WebGLUniformLocation | null => {
			if (!uniforms.has(name)) uniforms.set(name, gl.getUniformLocation(program, name));
			return uniforms.get(name)!;
		};
		gl.canvas.width = width;
		gl.canvas.height = height;
		gl.viewport(0, 0, width, height);
		const texture = gl.createTexture();
		try {
			gl.activeTexture(gl.TEXTURE0);
			gl.bindTexture(gl.TEXTURE_2D_ARRAY, texture);
			gl.texStorage3D(gl.TEXTURE_2D_ARRAY, 1, gl.RGBA8, size, size, tiles.length);
			gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
			gl.texParameteri(gl.TEXTURE_2D_ARRAY, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
			tiles.forEach((tile, layer) => {
				gl.texSubImage3D(
					gl.TEXTURE_2D_ARRAY,
					0,
					0,
					0,
					layer,
					size,
					size,
					1,
					gl.RGBA,
					gl.UNSIGNED_BYTE,
					tile
				);
			});
			gl.useProgram(program);
			gl.uniform1i(at('uTiles'), 0);
			gl.uniform2f(at('uPixel'), 1 / width, 1 / height);
			gl.uniform1i(at('uChart'), plan.chart);
			gl.uniform1i(at('uTile'), size);
			gl.uniform2i(
				at('uLevel'),
				chartColumns(plan.chart, plan.level) * size,
				chartRows(plan.chart, plan.level) * size
			);
			gl.uniform1i(at('uLevelColumns'), chartColumns(plan.chart, plan.level));
			gl.uniform2i(at('uFirst'), plan.column0, plan.row0);
			gl.uniform2i(at('uGrid'), plan.columns, plan.rows);
			gl.uniform1f(at('uPeak'), plan.peakShare);
			const rays = rayUniforms(frame);
			gl.uniform3fv(at('uRight'), rays.uRight);
			gl.uniform3fv(at('uUp'), rays.uUp);
			gl.uniform3fv(at('uForward'), rays.uForward);
			gl.uniform2fv(at('uHalf'), rays.uHalf);
			gl.bindBuffer(gl.ARRAY_BUFFER, this.corners);
			gl.enableVertexAttribArray(0);
			gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
			gl.drawArrays(gl.TRIANGLES, 0, 3);
			const data = new Uint8ClampedArray(width * height * 4);
			gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, data);
			if (gl.isContextLost()) throw new Error('star map context lost');
			return { data, width, height };
		} finally {
			gl.deleteTexture(texture);
			// A canvas of no size holds no picture.
			gl.canvas.width = 1;
			gl.canvas.height = 1;
		}
	}
}

let painter: Painter | null = null;

function sharedPainter(): Painter {
	if (painter && !painter.gl.isContextLost()) return painter;
	const held = webgl2Canvas({ alpha: false, antialias: false, depth: false, stencil: false });
	if (!held) throw new Error('star map needs WebGL 2');
	painter = new Painter(held.gl);
	return painter;
}

/** Frees the context of the tile sky. The next paint makes another. */
export function releaseTilePainter(): void {
	painter?.gl.getExtension('WEBGL_lose_context')?.loseContext();
	painter = null;
}

export class TileSkySource implements SkySource {
	constructor(private readonly pyramid: SkyPyramid) {}

	/** Rejects when a tile does not load, when `signal` aborts, and where the
	 *  device has no WebGL 2. */
	async paint(
		frame: ChartFrame,
		width: number,
		height: number,
		signal?: AbortSignal
	): Promise<Pixels | null> {
		const plan = planSky(this.pyramid, frame, width, height);
		if (!plan) return null;
		// A device that cannot paint the tiles does not download them.
		sharedPainter();
		const held = await Promise.allSettled(
			plan.tiles.map(({ cap, level, x, y }) =>
				acquireBitmap(tileUrl(this.pyramid, cap, level, x, y), null, false, signal, true)
			)
		);
		try {
			const tiles = held.map((tile) => {
				if (tile.status === 'rejected') throw tile.reason;
				if (!tile.value) throw new Error('star map tile did not decode');
				return tile.value.bitmap;
			});
			return sharedPainter().paint(this.pyramid, plan, tiles, frame, width, height);
		} finally {
			for (const tile of held) {
				if (tile.status === 'fulfilled' && tile.value) releaseBitmap(tile.value.key);
			}
		}
	}

	yields(frame: ChartFrame, width: number, height: number, step: number): boolean {
		const plan = planSky(this.pyramid, frame, width, height);
		return !!plan && planYields(plan, step, this.pyramid.tile_size);
	}

	/** A pyramid does not change while the page is open. */
	onChange(): () => void {
		return () => {};
	}
}
