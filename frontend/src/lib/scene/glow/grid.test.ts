import { afterEach, describe, expect, it, vi } from 'vitest';
import { configureHost } from '$lib/host';
import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { NestFormatError } from '$lib/scene/dust/nest';
import {
	fetchGlowMetadata,
	fetchGlowVolume,
	glowCurve,
	tableAxis,
	type GlowMetadata
} from './grid';

const fetchFile = vi.hoisted(() => vi.fn());

vi.mock('$lib/fetch/extrasolar/files', async (importActual) => ({
	...(await importActual<typeof import('$lib/fetch/extrasolar/files')>()),
	fetchExtrasolarFile: fetchFile
}));

const tier = (name: string) => ({
	size: 2,
	shells: 2,
	scale_pc: 20,
	reach_pc: 400_000,
	files: { a: { path: `${name}/a.bin.gz`, bytes: 1 }, b: { path: `${name}/b.bin.gz`, bytes: 1 } }
});
const META = {
	format: 1,
	token: '0123456789abcdef',
	distribution: 'open',
	texture_scale: 128,
	neutral_tint: 0.46,
	table: {
		magnitudes: [-20, -19.5],
		place_soft: [0, 0.5],
		colour: [
			[0.3, 0.3, 0.4],
			[0.2, 0.3, 0.5]
		]
	},
	inputs: { tree: '222c4b2dbfb4419b', dust: 'cda0ccc3900bbf23' },
	tiers: { high: tier('high'), low: tier('low') }
} as unknown as GlowMetadata;

afterEach(() => {
	fetchFile.mockReset();
	vi.unstubAllGlobals();
	configureHost({});
});

let hosts = 0;

/** Each call serves from a base URL of its own, so no test reads the metadata
 *  another one kept. */
function serve(status: number, body: unknown = META) {
	configureHost({ extrasolarUrl: `https://data${++hosts}.example` });
	const fetch = vi.fn(async () => new Response(JSON.stringify(body), { status }));
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

describe('the glow metadata', () => {
	it('is read from v1/glow/', async () => {
		const fetch = serve(200);
		expect(await fetchGlowMetadata()).toEqual(META);
		expect(String((fetch.mock.calls[0] as unknown[])[0])).toContain('/v1/glow/metadata.json');
	});

	it('is none where the host has no grid, with no error', async () => {
		serve(404);
		expect(await fetchGlowMetadata()).toBeNull();
	});

	it('refuses a format it cannot read', async () => {
		serve(200, { ...META, format: 2 });
		await expect(fetchGlowMetadata()).rejects.toThrow(NestFormatError);
	});

	it('is asked for once per host', async () => {
		const fetch = serve(200);
		const first = await fetchGlowMetadata();
		expect(await fetchGlowMetadata()).toBe(first);
		expect(fetch).toHaveBeenCalledTimes(1);
	});

	it('refuses a cut table whose magnitudes are not evenly spaced', async () => {
		const table = {
			magnitudes: [-20, -19.5, -18.5],
			place_soft: [0, 0.5, 1],
			colour: [...META.table.colour, [0.1, 0.3, 0.6]]
		};
		serve(200, { ...META, table });
		await expect(fetchGlowMetadata()).rejects.toThrow(NestFormatError);
	});
});

describe('the axis of the cut table', () => {
	it('is its first magnitude and its step', () => {
		expect(tableAxis(META)).toEqual({ first: -20, step: 0.5 });
		const table = { ...META.table, magnitudes: [-5, -4.9, -4.8, -4.7] };
		const axis = tableAxis({ ...META, table });
		expect(axis.first).toBe(-5);
		expect(axis.step).toBeCloseTo(0.1, 12);
	});

	it('needs two magnitudes or more', () => {
		const table = { ...META.table, magnitudes: [-20] };
		expect(() => tableAxis({ ...META, table })).toThrow(NestFormatError);
	});
});

describe('the glow textures', () => {
	it('come through the extrasolar fetch under the glow prefix', async () => {
		fetchFile.mockResolvedValue({ kind: KIND_VOLUME, uint16: () => new Uint16Array(32) });
		const volume = await fetchGlowVolume(META, 'low');
		expect(volume.a).toHaveLength(32);
		expect(fetchFile).toHaveBeenCalledWith('low/a.bin.gz', META.token, {
			prefix: 'glow',
			priority: 'low'
		});
	});

	it('come with coarse copies where the tier has room for them', async () => {
		const meta = { ...META, tiers: { ...META.tiers, low: { ...META.tiers.low, size: 6 } } };
		fetchFile.mockResolvedValue({ kind: KIND_VOLUME, uint16: () => new Uint16Array(288) });
		const { coarse } = await fetchGlowVolume(meta, 'low');
		const { width, height, levels } = coarse!.layout;
		expect(levels.map((l) => l.inner)).toEqual([2]);
		expect(coarse!.a).toHaveLength(width * height * 2 * 4);
		fetchFile.mockResolvedValue({ kind: KIND_VOLUME, uint16: () => new Uint16Array(32) });
		expect((await fetchGlowVolume(META, 'low')).coarse).toBeNull();
	});

	it('are refused when a file is not a volume', async () => {
		fetchFile.mockResolvedValue({ kind: 3, uint16: () => new Uint16Array(32) });
		await expect(fetchGlowVolume(META, 'high')).rejects.toThrow(NestFormatError);
	});

	it('are refused when a file holds more or fewer texels than its tier', async () => {
		for (const count of [28, 36]) {
			fetchFile.mockResolvedValue({ kind: KIND_VOLUME, uint16: () => new Uint16Array(count) });
			await expect(fetchGlowVolume(META, 'low')).rejects.toThrow(NestFormatError);
		}
	});
});

it('packs the soft table and its colour for the march', () => {
	expect(Array.from(glowCurve(META))).toEqual(
		[0, 0.3, 0.3, 0.4, 0.5, 0.2, 0.3, 0.5].map((x) => Math.fround(x))
	);
});
