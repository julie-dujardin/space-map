import { afterEach, describe, expect, it, vi } from 'vitest';
import { configureHost } from '$lib/host';
import { KIND_VOLUME } from '$lib/fetch/extrasolar/container';
import { ExtrasolarStaleError } from '$lib/fetch/extrasolar/files';
import { NestFormatError, fetchNestLevels, fetchNestMetadata, type NestMetadata } from './nest';

const fetchFile = vi.hoisted(() => vi.fn());

vi.mock('$lib/fetch/extrasolar/files', async (importActual) => ({
	...(await importActual<typeof import('$lib/fetch/extrasolar/files')>()),
	fetchExtrasolarFile: fetchFile
}));

const file = (path: string) => ({ path, size: [2, 2, 2], bytes: 8 });
const META = {
	format: 1,
	token: '0123456789abcdef',
	levels: [0, 1].map((level) => ({
		level,
		half_extent_pc: [10, 10, 10],
		floor: 1e-6,
		top: 0.1,
		high: file(`levels/${level}_high.bin.gz`),
		low: file(`levels/${level}_low.bin.gz`)
	}))
} as unknown as NestMetadata;

const volume = (kind = KIND_VOLUME) => ({ kind, uint8: () => new Uint8Array(8) });

let hosts = 0;
/** A base URL of its own, so no test reads the metadata another one kept. */
const newHost = () => configureHost({ extrasolarUrl: `https://data${++hosts}.example` });

afterEach(() => {
	fetchFile.mockReset();
	vi.unstubAllGlobals();
	configureHost({});
});

describe('the nest files', () => {
	it('go through the extrasolar fetch, so a token from another export prompts a reload', async () => {
		fetchFile.mockResolvedValue(volume());
		const levels = await fetchNestLevels(META, 'low');
		expect(levels).toHaveLength(2);
		expect(fetchFile).toHaveBeenCalledWith('levels/0_low.bin.gz', META.token, {
			prefix: 'dust',
			priority: 'low'
		});
		expect(fetchFile).toHaveBeenCalledWith('levels/1_low.bin.gz', META.token, {
			prefix: 'dust',
			priority: 'low'
		});
	});

	it('pass on the stale error of a file', async () => {
		fetchFile.mockRejectedValue(new ExtrasolarStaleError('levels/0_low.bin.gz', 'a', 'b'));
		await expect(fetchNestLevels(META, 'low')).rejects.toThrow(ExtrasolarStaleError);
	});

	it('are refused when the container is not a volume', async () => {
		fetchFile.mockResolvedValue(volume(3));
		await expect(fetchNestLevels(META, 'high')).rejects.toThrow(NestFormatError);
	});

	it('are refused when a level holds more or fewer texels than its size', async () => {
		for (const count of [7, 9]) {
			fetchFile.mockResolvedValue({ kind: KIND_VOLUME, uint8: () => new Uint8Array(count) });
			await expect(fetchNestLevels(META, 'low')).rejects.toThrow(NestFormatError);
		}
	});
});

describe('the nest metadata', () => {
	it('is refused when it is of another format', async () => {
		newHost();
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response(JSON.stringify({ ...META, format: 2 }), { status: 200 }))
		);
		await expect(fetchNestMetadata()).rejects.toThrow(NestFormatError);
	});

	it.each([403, 401, 410])('ends the load for a %i', async (status) => {
		newHost();
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('', { status }))
		);
		await expect(fetchNestMetadata()).rejects.toThrow(NestFormatError);
	});

	it('ends the load for a page that is not JSON', async () => {
		newHost();
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('<!doctype html><title>Home</title>', { status: 200 }))
		);
		await expect(fetchNestMetadata()).rejects.toThrow(NestFormatError);
	});

	it.each([408, 429])('stays retryable for a %i', async (status) => {
		newHost();
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('', { status }))
		);
		const err = await fetchNestMetadata().catch((e: unknown) => e);
		expect(err).toBeInstanceOf(Error);
		expect(err).not.toBeInstanceOf(NestFormatError);
	});

	it('stays retryable for a server error or a dropped connection', async () => {
		newHost();
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('', { status: 503 }))
		);
		const server = await fetchNestMetadata().catch((e: unknown) => e);
		expect(server).toBeInstanceOf(Error);
		expect(server).not.toBeInstanceOf(NestFormatError);
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => {
				throw new TypeError('network error');
			})
		);
		const network = await fetchNestMetadata().catch((e: unknown) => e);
		expect(network).toBeInstanceOf(TypeError);
	});

	it('is asked for once per host, and again after a failure', async () => {
		newHost();
		const fetch = vi.fn(async () => new Response('', { status: 503 }));
		vi.stubGlobal('fetch', fetch);
		await expect(fetchNestMetadata()).rejects.toThrow();
		fetch.mockImplementation(async () => new Response(JSON.stringify(META), { status: 200 }));
		const [a, b] = await Promise.all([fetchNestMetadata(), fetchNestMetadata()]);
		expect(a).toEqual(META);
		expect(b).toBe(a);
		expect(await fetchNestMetadata()).toBe(a);
		expect(fetch).toHaveBeenCalledTimes(2);
		newHost();
		await fetchNestMetadata();
		expect(fetch).toHaveBeenCalledTimes(3);
	});

	it('is absent on a host with no nest', async () => {
		newHost();
		vi.stubGlobal(
			'fetch',
			vi.fn(async () => new Response('', { status: 404 }))
		);
		expect(await fetchNestMetadata()).toBeNull();
	});
});
