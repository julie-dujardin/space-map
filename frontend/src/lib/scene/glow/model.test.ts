import { afterEach, describe, expect, it, vi } from 'vitest';
import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { NestFormatError } from '$lib/scene/dust/nest';
import { checkModel, fetchModelVolume, modelColours, modelGlsl, type GlowModel } from './model';
import { glslFloat } from '$lib/scene/dust/glsl';

const fetchFile = vi.hoisted(() => vi.fn());

vi.mock('$lib/fetch/extrasolar/files', async (importActual) => ({
	...(await importActual<typeof import('$lib/fetch/extrasolar/files')>()),
	fetchExtrasolarFile: fetchFile
}));

afterEach(() => fetchFile.mockReset());

const rows = (n: number) =>
	Array.from({ length: n }, () => [0.3, 0.3, 0.4] as [number, number, number]);

/** The served block's shape, at a small size. */
const MODEL: GlowModel = {
	model: true,
	texture_scale: 16384,
	centre_pc: [8277, 0, -21],
	boxes: {
		inner: { half_extent_pc: [24000, 24000, 3000], z_map: 'asinh', z_scale_pc: 150 },
		outer: { half_extent_pc: [64000, 64000, 64000], z_map: 'linear', z_scale_pc: 0 }
	},
	tiers: {
		high: {
			inner: { size: [4, 4, 2], path: 'high/model-inner.bin.gz', bytes: 1 },
			outer: { size: [2, 2, 2], path: 'high/model-outer.bin.gz', bytes: 1 }
		},
		low: {
			inner: { size: [2, 2, 2], path: 'low/model-inner.bin.gz', bytes: 1 },
			outer: { size: [2, 2, 2], path: 'low/model-outer.bin.gz', bytes: 1 }
		}
	},
	colour: {
		radius_step_pc: 1000,
		radii: 31,
		height_step_pc: 1000,
		heights: 2,
		reach_pc: 30000,
		shells_pc: [45000, 55000],
		rgb: rows(65)
	},
	catalogue_fade_pc: [2000, 4000],
	far_side_arms: 1
};

describe('the model block', () => {
	it('is read when it is whole', () => {
		expect(() => checkModel(MODEL)).not.toThrow();
		expect(() => checkModel({ ...MODEL, catalogue_fade_pc: null })).not.toThrow();
	});

	it('is a format error when the march could not read it', () => {
		const colour = { ...MODEL.colour, rgb: rows(64) };
		expect(() => checkModel({ ...MODEL, colour })).toThrow(NestFormatError);
		const inner = { ...MODEL.boxes.inner, z_scale_pc: 0 };
		expect(() => checkModel({ ...MODEL, boxes: { ...MODEL.boxes, inner } })).toThrow(
			NestFormatError
		);
		expect(() => checkModel({ ...MODEL, catalogue_fade_pc: [4000, 2000] })).toThrow(
			NestFormatError
		);
		expect(() => checkModel({ ...MODEL, texture_scale: 0 })).toThrow(NestFormatError);
	});
});

describe('the model volumes', () => {
	it('come under the glow prefix and the grid’s token, one per box', async () => {
		fetchFile.mockImplementation(async (path: string) => ({
			kind: KIND_VOLUME,
			uint16: () => new Uint16Array(path.includes('inner') ? 32 : 8)
		}));
		const volume = await fetchModelVolume('0123456789abcdef', MODEL, 'high');
		expect(volume.inner.size).toEqual([4, 4, 2]);
		expect(volume.inner.data).toHaveLength(32);
		expect(volume.outer.data).toHaveLength(8);
		expect(fetchFile).toHaveBeenCalledWith('high/model-inner.bin.gz', '0123456789abcdef', {
			prefix: 'glow',
			priority: 'low'
		});
	});

	it('are refused when a file is not a volume or holds another count of texels', async () => {
		fetchFile.mockResolvedValue({ kind: 3, uint16: () => new Uint16Array(32) });
		await expect(fetchModelVolume('t', MODEL, 'high')).rejects.toThrow(NestFormatError);
		fetchFile.mockResolvedValue({ kind: KIND_VOLUME, uint16: () => new Uint16Array(7) });
		await expect(fetchModelVolume('t', MODEL, 'low')).rejects.toThrow(NestFormatError);
	});
});

describe('the march’s model code', () => {
	it('is a weight of 1 and no light without a model, so the march draws as before', () => {
		const glsl = modelGlsl(null, 128);
		expect(glsl).toContain('float catalogueWeight(highp vec3 p) { return 1.0; }');
		expect(glsl).toContain('vec3 modelLight(highp vec3 p) { return vec3(0.0); }');
		expect(glsl).not.toContain('sampler3D');
	});

	it('reads the boxes as the format says, on the grid’s scale', () => {
		const glsl = modelGlsl(MODEL, 128);
		expect(glsl).toContain('uniform vec3 uModelColour[65];');
		// The inner box maps height through asinh, the outer one linearly.
		expect(glsl).toContain(`asinh(g.z / 150.0) * ${glslFloat(0.5 / Math.asinh(20))}`);
		expect(glsl).toContain(`g.z * ${glslFloat(0.5 / 64000)}`);
		expect(glsl).toContain(`L * ${glslFloat(128 / 16384)} * modelColour(g)`);
		// The shells past the reach: two edges, rows 62 to 64.
		expect(glsl.match(/k \+= r >= /g)).toHaveLength(2);
		expect(glsl).toContain('uModelColour[62 + k]');
		// Each fetch sits in a branch of its own.
		expect(glsl.match(/textureLod/g)).toHaveLength(2);
		expect(glsl).not.toMatch(/\?[^;]*textureLod/);
	});

	it('fades the catalogue over the distances of the block, or not at all', () => {
		expect(modelGlsl(MODEL, 128)).toContain('(length(p) - 2000.0) * 0.0005');
		expect(modelGlsl({ ...MODEL, catalogue_fade_pc: null }, 128)).toMatch(
			/catalogueWeight\(highp vec3 p\) \{\s*return 1\.0;/
		);
	});

	it('packs the colour table as one vec3 a row', () => {
		expect(modelColours(MODEL)).toHaveLength(65 * 3);
	});
});
