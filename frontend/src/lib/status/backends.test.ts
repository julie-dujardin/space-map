import { afterEach, describe, expect, it, vi } from 'vitest';

const env = vi.hoisted(() => ({ PUBLIC_MEILI_URL: '' }));
const urls = vi.hoisted(() => ({ tilesUrl: '' }));
vi.mock('$env/dynamic/public', () => ({ env }));
vi.mock('$lib/host', () => ({
	host: () => ({
		dataUrl: 'https://data.example',
		liveUrl: 'https://live.example',
		tilesUrl: urls.tilesUrl
	})
}));
vi.mock('$lib/paraglide/messages.js', () => ({
	status_service_search: () => 'Search',
	status_service_live: () => 'Spacecraft tracking',
	status_service_tiles: () => 'Surface tiles'
}));

import { backends, probe, type Backend } from './backends';

const ABOUT_DATA = {
	systems: [
		{
			worlds: [
				{ maps: [{ id: 'naif-399_clouds' }, { id: 'naif-399', frames: 12, tiles: {} }] },
				{ maps: [{ id: 'naif-499', tiles: {} }] }
			]
		}
	]
};

function backend(url: string): Backend {
	return { id: 'search', label: () => 'Search', url: () => url };
}

afterEach(() => {
	vi.unstubAllGlobals();
	vi.restoreAllMocks();
});

describe('backends', () => {
	it('gives search and tracking the address that their probe asks', () => {
		env.PUBLIC_MEILI_URL = 'https://search.example/';
		urls.tilesUrl = '';
		expect(backends().map((service) => [service.id, service.url()])).toEqual([
			['search', 'https://search.example/health'],
			['live', 'https://live.example/v1/activity.json']
		]);
	});

	it('has no search or tiles where the deployment turns them off', () => {
		env.PUBLIC_MEILI_URL = '';
		urls.tilesUrl = '';
		expect(backends().map((service) => service.id)).toEqual(['live']);
	});

	// The edge keeps a tile, and would answer for a server that is down.
	it('asks for a tile that the export names, past the edge cache', async () => {
		urls.tilesUrl = 'https://tiles.example';
		const fetch = vi.fn(() => Promise.resolve(Response.json(ABOUT_DATA)));
		vi.stubGlobal('fetch', fetch);
		const tiles = backends().find((service) => service.id === 'tiles')!;
		vi.spyOn(Date, 'now').mockReturnValueOnce(1).mockReturnValueOnce(2);
		expect([await tiles.url(), await tiles.url()]).toEqual([
			'https://tiles.example/v1/tiles/naif-499/0/0/0.webp?probe=1',
			'https://tiles.example/v1/tiles/naif-499/0/0/0.webp?probe=2'
		]);
		// The export is read once: later probes ask the tile host alone.
		expect(fetch).toHaveBeenCalledTimes(1);
	});
});

describe('probe', () => {
	it.each([
		{ name: 'a success', answer: () => Promise.resolve(new Response('{}')), up: true },
		{
			name: 'an error status',
			answer: () => Promise.resolve(new Response('', { status: 503 })),
			up: false
		},
		{ name: 'no answer', answer: () => Promise.reject(new TypeError('Failed to fetch')), up: false }
	])('$name → $up', async ({ answer, up }) => {
		vi.stubGlobal('fetch', vi.fn(answer));
		expect(await probe(backend('https://search.example/health'))).toBe(up);
	});

	it('reads a service as down when its address cannot be found', async () => {
		const fetch = vi.fn();
		vi.stubGlobal('fetch', fetch);
		const lost: Backend = { ...backend(''), url: () => Promise.reject(new Error('no pyramid')) };
		expect(await probe(lost)).toBe(false);
		expect(fetch).not.toHaveBeenCalled();
	});

	// A stored answer would read as up while the service is down.
	it('does not read the cache', async () => {
		const fetch = vi.fn<typeof globalThis.fetch>(() => Promise.resolve(new Response('{}')));
		vi.stubGlobal('fetch', fetch);
		await probe(backend('https://search.example/health'));
		expect(fetch.mock.calls[0][1]).toMatchObject({ cache: 'no-store' });
	});
});
