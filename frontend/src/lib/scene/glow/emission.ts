/**
 * Light that is not starlight (`docs/export-format/glow.md`, "Emission"): H-alpha
 * near the Sun, starlight that dust scatters, and the far H II regions. All three
 * are models scaled to observed totals, so they count as model light.
 *
 * H-alpha and the scattered light go in the glow's march, each with one fetch
 * where it can be non-zero. The far regions are sprites (`regions.ts`).
 */

import type { WebGLRenderer } from 'three';
import { KIND_TABLE, KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { fetchExtrasolarFile } from '$lib/fetch/extrasolar/files';
import { K_RGB, MAG_LN } from '$lib/scene/dust/extinction';
import { VolumeTextures } from '$lib/scene/dust/march';
import { NestFormatError } from '$lib/scene/dust/nest';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import type { GlowGridTier } from './grid';
import { glslFloat, glslVec3 } from '$lib/scene/dust/glsl';

export interface EmissionFile {
	size: Vec3;
	path: string;
	bytes: number;
}

export interface GlowEmission {
	lines: { colour: Vec3; k_rgb: Vec3 };
	halpha: {
		model: boolean;
		half_extent_pc: Vec3;
		tiers: Record<GlowGridTier, EmissionFile & { floor: number; top: number }>;
	};
	scatter: {
		model: boolean;
		albedo: Vec3;
		tau_per_mag: number;
		centre_pc: Vec3;
		half_extent_pc: Vec3;
		z_map: 'asinh' | 'linear';
		z_scale_pc: number;
		form: {
			channels: number;
			texture_scale: number;
			shield: { log10_density_nodes: number[]; factor: number[] };
			colour: {
				radii: number;
				r_max_pc: number;
				distances: number;
				d_scale_pc: number;
				d_max_pc: number;
				/** [distance node][radius node], each row summing to 1. */
				rgb: Vec3[][];
			};
		};
		tiers: Record<GlowGridTier, EmissionFile>;
	};
	regions: { path: string; bytes: number; rows: number };
}

/** Which parts draw. All of them in the app; the gates turn them off. */
export interface EmissionParts {
	halpha: boolean;
	scatter: boolean;
	regions: boolean;
}

export const ALL_PARTS: EmissionParts = { halpha: true, scatter: true, regions: true };
export const NO_PARTS: EmissionParts = { halpha: false, scatter: false, regions: false };

/** The far H II regions: one row each, on nest axes in pc. */
export interface EmissionRegions {
	x: Float32Array;
	y: Float32Array;
	z: Float32Array;
	sigma: Float32Array;
	/** R + G + B display flux at 10 pc, with no dust. */
	light: Float32Array;
}

/** One tier of the emission in memory. */
export interface EmissionVolume {
	halpha: { size: Vec3; data: Uint8Array };
	scatter: { size: Vec3; data: Uint16Array };
	regions: EmissionRegions;
}

const isSize = (v: unknown): boolean =>
	Array.isArray(v) && v.length === 3 && v.every((x) => Number.isInteger(x) && x > 0);

/** A block the march cannot read is a format error, so the load ends there. */
export function checkEmission(emission: GlowEmission): void {
	const fail = (what: string) => {
		throw new NestFormatError(`glow metadata.json: emission ${what}`);
	};
	const { halpha, scatter, lines } = emission;
	if (lines.colour.length !== 3 || lines.k_rgb.length !== 3) fail('lines');
	if (!halpha.half_extent_pc.every((x) => x > 0)) fail('halpha box');
	for (const tier of Object.values(halpha.tiers)) {
		if (!isSize(tier.size) || !(tier.floor > 0) || !(tier.top > tier.floor)) fail('halpha tier');
	}
	if (!scatter.half_extent_pc.every((x) => x > 0)) fail('scatter box');
	if (scatter.z_map === 'asinh' ? !(scatter.z_scale_pc > 0) : scatter.z_map !== 'linear') {
		fail('scatter z map');
	}
	const { form } = scatter;
	// The march reads one channel coloured by the table.
	if (form.channels !== 1 || !(form.texture_scale > 0)) fail('scatter form');
	const { colour, shield } = form;
	if (colour.radii < 2 || colour.distances < 2 || colour.rgb.length !== colour.distances) {
		fail('scatter colour');
	}
	if (colour.rgb.some((row) => row.length !== colour.radii)) fail('scatter colour rows');
	const nodes = shield.log10_density_nodes;
	if (nodes.length < 2 || nodes.length !== shield.factor.length) fail('scatter shield');
	const step = (nodes[nodes.length - 1] - nodes[0]) / (nodes.length - 1);
	if (!(step > 0) || nodes.some((x, i) => Math.abs(x - (nodes[0] + i * step)) > 1e-6 * step)) {
		fail('scatter shield nodes');
	}
	for (const tier of Object.values(scatter.tiers)) if (!isSize(tier.size)) fail('scatter tier');
}

async function fetchVolume(token: string, file: EmissionFile, column: 'codes' | 'texels') {
	const container = await fetchExtrasolarFile(file.path, token, {
		prefix: 'glow',
		priority: 'low'
	});
	if (container.kind !== KIND_VOLUME) {
		throw new NestFormatError(`glow ${file.path}: kind ${container.kind}, not a volume`);
	}
	const data = column === 'codes' ? container.uint8(column) : container.uint16(column);
	if (data.length !== file.size[0] * file.size[1] * file.size[2]) {
		throw new NestFormatError(`glow ${file.path}: texel count`);
	}
	return data;
}

async function fetchRegions(token: string, emission: GlowEmission): Promise<EmissionRegions> {
	const { path } = emission.regions;
	const container = await fetchExtrasolarFile(path, token, { prefix: 'glow', priority: 'low' });
	if (container.kind !== KIND_TABLE) {
		throw new NestFormatError(`glow ${path}: kind ${container.kind}, not a table`);
	}
	return {
		x: container.float32('x'),
		y: container.float32('y'),
		z: container.float32('z'),
		sigma: container.float32('sigma_pc'),
		light: container.float32('light')
	};
}

export async function fetchEmission(
	token: string,
	emission: GlowEmission,
	tier: GlowGridTier
): Promise<EmissionVolume> {
	const h = emission.halpha.tiers[tier];
	const s = emission.scatter.tiers[tier];
	const [halpha, scatter, regions] = await Promise.all([
		fetchVolume(token, h, 'codes'),
		fetchVolume(token, s, 'texels'),
		fetchRegions(token, emission)
	]);
	return {
		halpha: { size: h.size, data: halpha as Uint8Array },
		scatter: { size: s.size, data: scatter as Uint16Array },
		regions
	};
}

/** J's colour table as RGBA texels, radius across and distance down. */
export function scatterColours(emission: GlowEmission): Float32Array {
	const { rgb, radii, distances } = emission.scatter.form.colour;
	const out = new Float32Array(radii * distances * 4);
	rgb.forEach((row, k) =>
		row.forEach((c, i) => out.set([c[0], c[1], c[2], 1], 4 * (k * radii + i)))
	);
	return out;
}

/** Per channel, the natural-log depth of a column of 1 mag A0 for the lines. */
export function lineDepth(emission: GlowEmission): Vec3 {
	return emission.lines.k_rgb.map((k) => MAG_LN * k) as Vec3;
}

/**
 * GLSL of the march's emission terms, on the grid's scale `gridScale`, for the
 * parts that draw:
 * - `scatteredLight(p, rho)`: starlight scattered by dust of density `rho`
 *   (A0 mag/pc) at `p`, per channel. It takes the stars' transmission.
 * - `lineLight(p, column, rise, ds)`: H-alpha's light of a step of `ds` pc at
 *   `p`, seen through `column` (A0 mag) and its own `rise` over the step, at the
 *   lines' K.
 * Each reads its texture only where it can be non-zero, inside an `if`.
 */
export function emissionGlsl(
	emission: GlowEmission,
	parts: EmissionParts,
	tier: GlowGridTier,
	gridScale: number
): string {
	const out: string[] = [];
	if (parts.halpha) {
		const { half_extent_pc: half, tiers } = emission.halpha;
		const { floor, top } = tiers[tier];
		const depth = lineDepth(emission);
		out.push(/* glsl */ `
uniform highp sampler3D uHalpha;
vec3 lineLight(highp vec3 p, highp float column, highp float rise, highp float ds) {
	if (any(greaterThan(abs(p), ${glslVec3(half)}))) return vec3(0.0);
	float code = textureLod(uHalpha, p * ${glslVec3(half.map((h) => 0.5 / h))} + 0.5, 0.0).r;
	vec3 j = ${glslFloat(floor * gridScale)} * (exp(code * ${glslFloat(Math.log1p(top / floor))}) - 1.0) * ${glslVec3(emission.lines.colour)};
	vec3 depth = rise * ${glslVec3(depth)};
	// The mean of the light through the step. A thin step needs the series.
	vec3 mean = rise > 0.01 ? (1.0 - exp(-depth)) / depth : 1.0 - 0.5 * depth;
	return j * exp(-column * ${glslVec3(depth)}) * mean * ds;
}`);
	}
	if (parts.scatter) {
		const s = emission.scatter;
		const { colour, shield } = s.form;
		const [hx, hy, hz] = s.half_extent_pc;
		const w =
			s.z_map === 'asinh'
				? `asinh(g.z / ${glslFloat(s.z_scale_pc)}) * ${glslFloat(0.5 / Math.asinh(hz / s.z_scale_pc))}`
				: `g.z * ${glslFloat(0.5 / hz)}`;
		const nodes = shield.log10_density_nodes;
		const step = (nodes[nodes.length - 1] - nodes[0]) / (nodes.length - 1);
		const factors = shield.factor.map(glslFloat).join(', ');
		// Albedo, the stars' K and tau per mag, and J's scale, as one factor.
		const k = s.albedo.map(
			(a, c) => a * K_RGB[c] * s.tau_per_mag * (gridScale / s.form.texture_scale)
		);
		out.push(/* glsl */ `
uniform highp sampler3D uScatterJ;
uniform highp sampler2D uScatterColour;
const float SHIELD[${shield.factor.length}] = float[${shield.factor.length}](${factors});

// The share of the grid's J that dust of density rho sees: dense dust shields itself.
float shield(highp float rho) {
	float t = clamp((log2(max(rho, 1e-12)) * 0.30102999566 - ${glslFloat(nodes[0])}) * ${glslFloat(1 / step)}, 0.0, ${(shield.factor.length - 1.001).toFixed(3)});
	int i = int(t);
	return mix(SHIELD[i], SHIELD[i + 1], t - float(i));
}

vec3 scatteredLight(highp vec3 p, highp float rho) {
	if (rho <= 0.0) return vec3(0.0);
	highp vec3 g = p - ${glslVec3(s.centre_pc)};
	if (any(greaterThan(abs(g), ${glslVec3(s.half_extent_pc)}))) return vec3(0.0);
	highp vec3 uvw = vec3(g.x * ${glslFloat(0.5 / hx)}, g.y * ${glslFloat(0.5 / hy)}, ${w}) + 0.5;
	float J = textureLod(uScatterJ, uvw, 0.0).r;
	float a = clamp(length(g.xy) * ${glslFloat(1 / colour.r_max_pc)}, 0.0, 1.0) * ${(colour.radii - 1).toFixed(1)};
	float b = clamp(log(1.0 + length(p) * ${glslFloat(1 / colour.d_scale_pc)}) * ${glslFloat(1 / Math.log1p(colour.d_max_pc / colour.d_scale_pc))}, 0.0, 1.0) * ${(colour.distances - 1).toFixed(1)};
	vec3 tint = textureLod(uScatterColour, (vec2(a, b) + 0.5) * ${`vec2(${glslFloat(1 / colour.radii)}, ${glslFloat(1 / colour.distances)})`}, 0.0).rgb;
	return ${glslVec3(k)} * (rho * J * shield(rho)) * tint;
}`);
	}
	return out.join('\n');
}

/** The samplers the march's emission terms read, in the order of their textures. */
export function emissionSamplers(parts: EmissionParts): string[] {
	return [
		...(parts.halpha ? ['uHalpha'] : []),
		...(parts.scatter ? ['uScatterJ', 'uScatterColour'] : [])
	];
}

/** The emission on the GPU: H-alpha and J upload a few slices a frame with the
 *  grid; J's colour table is small and goes up at once. */
export class EmissionTextures {
	private readonly halpha: VolumeTextures;
	private readonly scatter: VolumeTextures;
	private readonly colour: WebGLTexture;

	constructor(
		private readonly renderer: WebGLRenderer,
		volume: EmissionVolume,
		emission: GlowEmission
	) {
		this.halpha = new VolumeTextures(renderer, [volume.halpha], 'r8');
		this.scatter = new VolumeTextures(renderer, [volume.scatter], 'r16f');
		const gl = renderer.getContext() as WebGL2RenderingContext;
		const { radii, distances } = emission.scatter.form.colour;
		this.colour = gl.createTexture();
		renderer.state.bindTexture(gl.TEXTURE_2D, this.colour);
		gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA16F, radii, distances);
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
		gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
		gl.texSubImage2D(
			gl.TEXTURE_2D,
			0,
			0,
			0,
			radii,
			distances,
			gl.RGBA,
			gl.FLOAT,
			scatterColours(emission)
		);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
	}

	get uploaded(): boolean {
		return this.halpha.uploaded && this.scatter.uploaded;
	}

	step(): void {
		(this.halpha.uploaded ? this.scatter : this.halpha).step();
	}

	/** The textures of the parts that draw, in the order of `emissionSamplers`. */
	bindings(
		parts: EmissionParts,
		gl: WebGL2RenderingContext
	): { target: number; texture: WebGLTexture }[] {
		return [
			...(parts.halpha ? [{ target: gl.TEXTURE_3D, texture: this.halpha.textures[0] }] : []),
			...(parts.scatter
				? [
						{ target: gl.TEXTURE_3D, texture: this.scatter.textures[0] },
						{ target: gl.TEXTURE_2D, texture: this.colour }
					]
				: [])
		];
	}

	dispose(): void {
		this.halpha.dispose();
		this.scatter.dispose();
		(this.renderer.getContext() as WebGL2RenderingContext).deleteTexture(this.colour);
	}
}
