import { afterEach, beforeEach, describe, it, expect, vi } from 'vitest';

const env = vi.hoisted(() => ({}) as Record<string, string | undefined>);
vi.mock('$env/dynamic/private', () => ({ env }));

import { POST } from './+server';

const UID = '11fba2d9-b391-4a78-9745-56e5aaa8d1ba';

/** Calls the endpoint with `proof`, against a siteverify that answers with `verdict`. */
function ask(proof: string | undefined, verdict: unknown = { success: true }) {
	const fetcher = vi.fn(async () => Response.json(verdict));
	const request = new Request('http://localhost/api/search-key', {
		method: 'POST',
		body: JSON.stringify({ proof })
	});
	return { answer: POST({ request, fetch: fetcher } as never) as Promise<Response>, fetcher };
}

function payload(jwt: string): { apiKeyUid: string; exp: number; searchRules: unknown } {
	return JSON.parse(atob(jwt.split('.')[1]));
}

beforeEach(() => {
	for (const name of Object.keys(env)) delete env[name];
	env.MEILI_SEARCH_KEY = 'parent-key';
	env.MEILI_SEARCH_KEY_UID = UID;
	vi.spyOn(console, 'info').mockImplementation(() => {});
	vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

describe('POST /api/search-key', () => {
	it('answers 503 with no search key to sign with', async () => {
		delete env.MEILI_SEARCH_KEY;
		await expect(ask('token').answer).rejects.toMatchObject({ status: 503 });
	});

	it('asks nobody for proof without a secret', async () => {
		const { answer, fetcher } = ask(undefined);
		const res = await answer;
		const { key, ttl } = await res.json();
		expect(ttl).toBe(3600);
		expect(payload(key).apiKeyUid).toBe(UID);
		expect(payload(key).exp - Date.now() / 1000).toBeCloseTo(3600, -1);
		expect(res.headers.get('Cache-Control')).toBe('no-store');
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('checks and logs, and refuses nobody, when nothing is required', async () => {
		env.TURNSTILE_SECRET = 'secret';
		expect((await ask(undefined).answer).status).toBe(200);
		expect((await ask('made-up', { success: false }).answer).status).toBe(200);
		expect(console.info).toHaveBeenCalledTimes(2);
	});

	it('logs a secret Cloudflare does not know, and refuses nobody, when nothing is required', async () => {
		env.TURNSTILE_SECRET = 'mistyped';
		const unknown = { success: false, 'error-codes': ['invalid-input-secret'] };
		expect((await ask('token', unknown).answer).status).toBe(200);
		expect(console.error).toHaveBeenCalledWith('Cloudflare does not know TURNSTILE_SECRET');
	});

	it('answers 503 when proof is required and there is no secret to check it with', async () => {
		env.TURNSTILE_REQUIRE = 'search';
		await expect(ask('token').answer).rejects.toMatchObject({ status: 503 });
		await expect(ask(undefined).answer).rejects.toMatchObject({ status: 503 });
	});

	it('refuses a requirement it does not know, with or without a secret', async () => {
		env.TURNSTILE_REQUIRE = 'join';
		await expect(ask('token').answer).rejects.toThrow('join');
	});

	describe('with proof required', () => {
		beforeEach(() => {
			env.TURNSTILE_SECRET = 'secret';
			env.TURNSTILE_REQUIRE = 'search';
		});

		it('gives a key for a proof that holds', async () => {
			const { answer, fetcher } = ask('token', { success: true, action: 'search' });
			expect((await answer).status).toBe(200);
			expect(fetcher).toHaveBeenCalledOnce();
			expect(console.info).not.toHaveBeenCalled();
		});

		it('refuses a request with no proof, or with one that does not hold', async () => {
			await expect(ask(undefined).answer).rejects.toMatchObject({ status: 403 });
			await expect(ask('made-up', { success: false }).answer).rejects.toMatchObject({
				status: 403
			});
		});

		it('gives a key when Cloudflare cannot be asked', async () => {
			const faulty = { success: false, 'error-codes': ['internal-error'] };
			expect((await ask('token', faulty).answer).status).toBe(200);
		});

		it('answers 503 on a secret Cloudflare does not know', async () => {
			const unknown = { success: false, 'error-codes': ['invalid-input-secret'] };
			await expect(ask('token', unknown).answer).rejects.toMatchObject({ status: 503 });
		});
	});
});
