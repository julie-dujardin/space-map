import { readFileSync } from 'node:fs';
import { gzipSync } from 'node:zlib';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { configureHost } from '$lib/host';
import {
	ExtrasolarStaleError,
	extrasolarAllowed,
	extrasolarPath,
	extrasolarUrl,
	fetchExtrasolarFile,
	fetchExtrasolarJson,
	fetchExtrasolarMetadata,
	onExtrasolarStale
} from './files';

const TOKEN = '0123456789abcdef';
const node = readFileSync(new URL('./__fixtures__/node.bin.gz', import.meta.url));

function serveFixture(): ReturnType<typeof vi.fn> {
	const fetch = vi.fn(async () => new Response(node, { status: 200 }));
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

afterEach(() => {
	vi.unstubAllGlobals();
	configureHost({});
});

describe('extrasolar files', () => {
	it('builds URLs under the host base with the token', () => {
		configureHost({ extrasolarUrl: 'https://x.example/' });
		expect(extrasolarUrl(extrasolarPath('mw/node/{name}.bin.gz', { name: 'r07' }), TOKEN)).toBe(
			`https://x.example/v1/x/mw/node/r07.bin.gz?v=${TOKEN}`
		);
		expect(extrasolarPath('point-source/{level}/{pixel}.bin.gz', { level: 8, pixel: 335040 })).toBe(
			'point-source/8/335040.bin.gz'
		);
		expect(() => extrasolarPath('mw/node/{name}.bin.gz', {})).toThrow();
	});

	it('has no metadata and makes no request without a base URL', async () => {
		const fetch = serveFixture();
		expect(await fetchExtrasolarMetadata()).toBeNull();
		expect(fetch).not.toHaveBeenCalled();
	});

	it('gates on the distribution ladder of the host', () => {
		configureHost({ textures: 'open' });
		expect(extrasolarAllowed({ distribution: 'non-commercial' })).toBe(false);
		expect(extrasolarAllowed({})).toBe(true);
		configureHost({ textures: 'non-commercial' });
		expect(extrasolarAllowed({ distribution: 'non-commercial' })).toBe(true);
	});

	it('decodes a file whose token matches', async () => {
		configureHost({ extrasolarUrl: '/data' });
		const fetch = serveFixture();
		const container = await fetchExtrasolarFile('mw/node/r.bin.gz', TOKEN);
		expect(container.rows).toBe(5);
		expect(fetch.mock.calls[0][0]).toBe(`/data/v1/x/mw/node/r.bin.gz?v=${TOKEN}`);
	});

	it('rejects a file from another export and tells the stale listeners once', async () => {
		configureHost({ extrasolarUrl: '/data' });
		serveFixture();
		const stale = vi.fn();
		const off = onExtrasolarStale(stale);
		await expect(fetchExtrasolarFile('mw/node/r.bin.gz', 'ffffffffffffffff')).rejects.toThrow(
			ExtrasolarStaleError
		);
		await expect(fetchExtrasolarFile('mw/node/r0.bin.gz', 'ffffffffffffffff')).rejects.toThrow(
			ExtrasolarStaleError
		);
		expect(stale).toHaveBeenCalledTimes(1);
		off();
	});

	it('decodes a JSON file and checks its token field', async () => {
		configureHost({ extrasolarUrl: '/data' });
		const body = gzipSync(JSON.stringify({ token: TOKEN, hosts: [] }));
		const fetch = vi.fn<(url: string) => Promise<Response>>(
			async () => new Response(body, { status: 200 })
		);
		vi.stubGlobal('fetch', fetch);
		expect(await fetchExtrasolarJson('planets/index.json.gz', TOKEN)).toEqual({
			token: TOKEN,
			hosts: []
		});
		expect(fetch.mock.calls[0][0]).toBe(`/data/v1/x/planets/index.json.gz?v=${TOKEN}`);
		await expect(fetchExtrasolarJson('planets/index.json.gz', 'ffffffffffffffff')).rejects.toThrow(
			ExtrasolarStaleError
		);
	});
});
