import { afterEach, describe, expect, it, vi } from 'vitest';
import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { NestFormatError, type NestFarEntry } from '$lib/scene/dust/nest';
import { fetchFarDust, glowDensityGlsl } from './far-dust';
import { glslFloat } from '$lib/scene/dust/glsl';

const net = vi.hoisted(() => ({ meta: null as unknown, file: vi.fn() }));

vi.mock('$lib/scene/dust/nest', async (importActual) => ({
	...(await importActual<typeof import('$lib/scene/dust/nest')>()),
	fetchNestMetadata: async () => net.meta
}));
vi.mock('$lib/fetch/extrasolar/files', async (importActual) => ({
	...(await importActual<typeof import('$lib/fetch/extrasolar/files')>()),
	fetchExtrasolarFile: net.file
}));

afterEach(() => net.file.mockReset());

const FAR: NestFarEntry = {
	centre_pc: [8277, 0, -21],
	half_extent_pc: [24000, 24000, 3000],
	z_map: 'asinh',
	z_scale_pc: 150,
	floor: 1e-6,
	top: 4.02e-4,
	high: { path: 'high/far.bin.gz', size: [4, 4, 2], bytes: 1 },
	low: { path: 'low/far.bin.gz', size: [2, 2, 2], bytes: 1 }
};
const LEVELS = [
	{
		half: [20000, 20000, 2000] as [number, number, number],
		floor: 1e-6,
		span: 1,
		size: [2, 2, 2] as [number, number, number]
	},
	{
		half: [3000, 3000, 3000] as [number, number, number],
		floor: 1e-6,
		span: 1,
		size: [2, 2, 2] as [number, number, number]
	}
];

describe('the far dust', () => {
	it('is refused where the host draws no nest', async () => {
		net.meta = null;
		await expect(fetchFarDust('high')).rejects.toThrow(NestFormatError);
		expect(net.file).not.toHaveBeenCalled();
	});

	it('comes under the dust prefix and the nest’s token, by tier', async () => {
		net.meta = { token: 'nest', far: FAR };
		net.file.mockResolvedValue({ kind: KIND_VOLUME, uint8: () => new Uint8Array(8) });
		const far = await fetchFarDust('low');
		expect(far?.codes).toHaveLength(8);
		expect(net.file).toHaveBeenCalledWith('low/far.bin.gz', 'nest', {
			prefix: 'dust',
			priority: 'low'
		});
	});

	it('is refused when the file or the block is not what the reader needs', async () => {
		net.meta = { token: 'nest', far: FAR };
		net.file.mockResolvedValue({ kind: KIND_VOLUME, uint8: () => new Uint8Array(7) });
		await expect(fetchFarDust('low')).rejects.toThrow(NestFormatError);
		net.meta = { token: 'nest', far: { ...FAR, top: 0 } };
		await expect(fetchFarDust('low')).rejects.toThrow(NestFormatError);
	});
});

describe('the glow’s dust', () => {
	it('is the nest’s alone without far dust', () => {
		expect(glowDensityGlsl(LEVELS, null)).toBe(
			'highp float glowDensity(highp vec3 p) { return density(p); }'
		);
	});

	it('reads the far dust only where no level of the nest holds the point', () => {
		const glsl = glowDensityGlsl(LEVELS, FAR);
		expect(glsl).toContain(
			'if (all(lessThanEqual(a, vec3(20000.0, 20000.0, 2000.0))) || all(lessThanEqual(a, vec3(3000.0, 3000.0, 3000.0)))) return density(p);'
		);
		expect(glsl).toContain(`* ${glslFloat(Math.log1p(FAR.top / FAR.floor))}) - 1.0)`);
		expect(glsl.match(/textureLod/g)).toHaveLength(1);
	});
});
