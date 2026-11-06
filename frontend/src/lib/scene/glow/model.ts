/**
 * Model light of the whole Galaxy (`docs/export-format/glow.md`, "Model light"):
 * the light the catalogue lacks, smooth and with no stars. It sits in two boxes
 * about the Galactic centre, one R16F channel coloured by a table, so a sample
 * reads it with one fetch.
 *
 * The catalogue's grid fades out with distance from the Sun as the residual was
 * built, so from far away the glow is the model alone.
 */

import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { fetchExtrasolarFile } from '$lib/fetch/extrasolar/files';
import { NestFormatError } from '$lib/scene/dust/nest';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import type { GlowGridTier } from './grid';
import { glslFloat, glslVec3 } from '$lib/scene/dust/glsl';

export interface ModelBox {
	half_extent_pc: Vec3;
	z_map: 'asinh' | 'linear';
	z_scale_pc: number;
}

export interface ModelFile {
	size: Vec3;
	path: string;
	bytes: number;
}

export interface ModelColour {
	radius_step_pc: number;
	radii: number;
	height_step_pc: number;
	heights: number;
	reach_pc: number;
	shells_pc: number[];
	rgb: [number, number, number][];
}

export interface GlowModel {
	model: boolean;
	texture_scale: number;
	centre_pc: Vec3;
	boxes: { inner: ModelBox; outer: ModelBox };
	tiers: Record<GlowGridTier, { inner: ModelFile; outer: ModelFile }>;
	colour: ModelColour;
	/** Distances from the Sun over which the grid's light fades to 0. */
	catalogue_fade_pc: [number, number] | null;
	far_side_arms: number;
}

/** One tier of the model in memory: uint16 half floats, x fastest. */
export interface ModelVolume {
	inner: { size: Vec3; data: Uint16Array };
	outer: { size: Vec3; data: Uint16Array };
}

const isSize = (v: unknown): boolean =>
	Array.isArray(v) && v.length === 3 && v.every((x) => Number.isInteger(x) && x > 0);

/** A block the march cannot read is a format error, so the load ends there. */
export function checkModel(model: GlowModel): void {
	const fail = (what: string) => {
		throw new NestFormatError(`glow metadata.json: model ${what}`);
	};
	const { colour, boxes, tiers, catalogue_fade_pc: fade } = model;
	if (!(model.texture_scale > 0)) fail('texture_scale');
	if (colour.radii < 2 || colour.heights < 2) fail('colour grid');
	if (colour.rgb.length !== colour.radii * colour.heights + colour.shells_pc.length + 1) {
		fail('colour rows');
	}
	for (const box of [boxes.inner, boxes.outer]) {
		if (!box.half_extent_pc.every((x) => x > 0)) fail('box');
		if (box.z_map === 'asinh' ? !(box.z_scale_pc > 0) : box.z_map !== 'linear') fail('z map');
	}
	for (const tier of Object.values(tiers)) {
		if (!isSize(tier.inner.size) || !isSize(tier.outer.size)) fail('size');
	}
	if (fade && !(fade[1] > fade[0])) fail('catalogue_fade_pc');
}

async function fetchBox(token: string, file: ModelFile): Promise<Uint16Array> {
	const container = await fetchExtrasolarFile(file.path, token, {
		prefix: 'glow',
		priority: 'low'
	});
	if (container.kind !== KIND_VOLUME) {
		throw new NestFormatError(`glow ${file.path}: kind ${container.kind}, not a volume`);
	}
	const data = container.uint16('texels');
	const [nx, ny, nz] = file.size;
	if (data.length !== nx * ny * nz) throw new NestFormatError(`glow ${file.path}: texel count`);
	return data;
}

export async function fetchModelVolume(
	token: string,
	model: GlowModel,
	tier: GlowGridTier
): Promise<ModelVolume> {
	const { inner, outer } = model.tiers[tier];
	const [a, b] = await Promise.all([fetchBox(token, inner), fetchBox(token, outer)]);
	return { inner: { size: inner.size, data: a }, outer: { size: outer.size, data: b } };
}

/** The colour table as the march's uniform. */
export function modelColours(model: GlowModel): Float32Array {
	return new Float32Array(model.colour.rgb.flat());
}

/** Texture coordinate of `g` (pc from the centre) in a box, as GLSL. */
function boxUvw(box: ModelBox): string {
	const [hx, hy, hz] = box.half_extent_pc;
	const w =
		box.z_map === 'asinh'
			? `asinh(g.z / ${glslFloat(box.z_scale_pc)}) * ${glslFloat(0.5 / Math.asinh(hz / box.z_scale_pc))}`
			: `g.z * ${glslFloat(0.5 / hz)}`;
	return `vec3(g.x * ${glslFloat(0.5 / hx)}, g.y * ${glslFloat(0.5 / hy)}, ${w}) + 0.5`;
}

/**
 * GLSL of `catalogueWeight(p)`, the share of the grid's light at `p` (pc from
 * the Sun), and `modelLight(p)`, the model's light there per channel, on the
 * grid's scale `gridScale`. Without a model the weight is 1 and the light 0, so
 * the march draws as before.
 */
export function modelGlsl(model: GlowModel | null, gridScale: number): string {
	if (!model) {
		return /* glsl */ `
float catalogueWeight(highp vec3 p) { return 1.0; }
vec3 modelLight(highp vec3 p) { return vec3(0.0); }
`;
	}
	const { colour, boxes, catalogue_fade_pc: fade } = model;
	const { radii, heights } = colour;
	const plane = radii * heights;
	const shells = colour.shells_pc
		.map((edge) => `k += r >= ${glslFloat(edge)} ? 1 : 0;`)
		.join('\n\t\t');
	const weight = fade
		? `float t = clamp((length(p) - ${glslFloat(fade[0])}) * ${glslFloat(1 / (fade[1] - fade[0]))}, 0.0, 1.0);
	return 1.0 - t * t * (3.0 - 2.0 * t);`
		: 'return 1.0;';
	return /* glsl */ `
uniform highp sampler3D uModelInner;
uniform highp sampler3D uModelOuter;
uniform vec3 uModelColour[${colour.rgb.length}];

float catalogueWeight(highp vec3 p) {
	${weight}
}

vec3 modelColour(highp vec3 g) {
	float r = length(g);
	if (r >= ${glslFloat(colour.reach_pc)}) {
		int k = 0;
		${shells}
		return uModelColour[${plane} + k];
	}
	float a = clamp(length(g.xy) * ${glslFloat(1 / colour.radius_step_pc)}, 0.0, ${(radii - 1.001).toFixed(3)});
	float b = clamp(abs(g.z) * ${glslFloat(1 / colour.height_step_pc)}, 0.0, ${(heights - 1.001).toFixed(3)});
	int i = int(a);
	int j = int(b) * ${radii} + i;
	vec3 low = mix(uModelColour[j], uModelColour[j + 1], a - float(i));
	vec3 high = mix(uModelColour[j + ${radii}], uModelColour[j + ${radii + 1}], a - float(i));
	return mix(low, high, fract(b));
}

// The model's light at p per channel, on the grid's scale.
vec3 modelLight(highp vec3 p) {
	highp vec3 g = p - ${glslVec3(model.centre_pc)};
	highp vec3 a = abs(g);
	float L = 0.0;
	if (all(lessThanEqual(a, ${glslVec3(boxes.inner.half_extent_pc)}))) {
		L = textureLod(uModelInner, ${boxUvw(boxes.inner)}, 0.0).r;
	} else if (all(lessThanEqual(a, ${glslVec3(boxes.outer.half_extent_pc)}))) {
		L = textureLod(uModelOuter, ${boxUvw(boxes.outer)}, 0.0).r;
	}
	return L * ${glslFloat(gridScale / model.texture_scale)} * modelColour(g);
}
`;
}
