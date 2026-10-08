import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';

const env = vi.hoisted(() => ({}) as Record<string, string | undefined>);
vi.mock('$env/dynamic/private', () => ({ env }));

import { POST } from './+server';

const UID = '11fba2d9-b391-4a78-9745-56e5aaa8d1ba';

function ask() {
	const request = new Request('http://localhost/api/search-key', { method: 'POST' });
	return POST({ request } as never) as Promise<Response>;
}

function payload(jwt: string): { apiKeyUid: string; exp: number; searchRules: unknown } {
	return JSON.parse(atob(jwt.split('.')[1]));
}

beforeEach(() => {
	for (const name of Object.keys(env)) delete env[name];
	env.MEILI_SEARCH_KEY = 'parent-key';
	env.MEILI_SEARCH_KEY_UID = UID;
	vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

describe('POST /api/search-key', () => {
	it('answers 503 with no search key to sign with', async () => {
		delete env.MEILI_SEARCH_KEY;
		await expect(ask()).rejects.toMatchObject({ status: 503 });
	});

	it('signs a key that lasts one hour', async () => {
		const res = await ask();
		const { key, ttl } = await res.json();
		expect(ttl).toBe(3600);
		expect(payload(key).apiKeyUid).toBe(UID);
		expect(payload(key).exp - Date.now() / 1000).toBeCloseTo(3600, -1);
		expect(res.headers.get('Cache-Control')).toBe('no-store');
	});
});
