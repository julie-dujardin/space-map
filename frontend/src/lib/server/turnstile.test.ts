import { describe, it, expect, vi } from 'vitest';
import { checkProof, requiredActions } from './turnstile';

/** A stand-in for siteverify that answers with `verdict`. */
function cloudflare(verdict: unknown) {
	return vi.fn(async () => Response.json(verdict)) as unknown as typeof fetch;
}

describe('checkProof', () => {
	it('is absent with no token, and Cloudflare is not asked', async () => {
		const fetcher = cloudflare({ success: true });
		expect(await checkProof('secret', undefined, 'search', fetcher)).toBe('absent');
		expect(await checkProof('secret', '', 'search', fetcher)).toBe('absent');
		expect(await checkProof('secret', 42, 'search', fetcher)).toBe('absent');
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('refuses a token longer than Cloudflare makes, and does not ask', async () => {
		const fetcher = cloudflare({ success: true });
		expect(await checkProof('secret', 'x'.repeat(2049), 'search', fetcher)).toBe('refused');
		expect(fetcher).not.toHaveBeenCalled();
	});

	it('holds when Cloudflare vouches for the token', async () => {
		const fetcher = cloudflare({ success: true, action: 'search' });
		expect(await checkProof('secret', 'token', 'search', fetcher)).toBe('held');
		const [, init] = vi.mocked(fetcher).mock.calls[0];
		expect(JSON.parse(init?.body as string)).toEqual({ secret: 'secret', response: 'token' });
	});

	it('holds when Cloudflare names no action, as with its test keys', async () => {
		expect(await checkProof('secret', 'token', 'search', cloudflare({ success: true }))).toBe(
			'held'
		);
		const blank = cloudflare({ success: true, action: '' });
		expect(await checkProof('secret', 'token', 'search', blank)).toBe('held');
	});

	it('refuses a token made for another action', async () => {
		const fetcher = cloudflare({ success: true, action: 'join' });
		expect(await checkProof('secret', 'token', 'search', fetcher)).toBe('refused');
	});

	it('refuses a token Cloudflare does not vouch for', async () => {
		for (const code of ['invalid-input-response', 'timeout-or-duplicate']) {
			const fetcher = cloudflare({ success: false, 'error-codes': [code] });
			expect(await checkProof('secret', 'token', 'search', fetcher)).toBe('refused');
		}
		expect(await checkProof('secret', 'token', 'search', cloudflare({ success: false }))).toBe(
			'refused'
		);
	});

	it('is unchecked when Cloudflare gives no answer', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => {});
		const down = vi.fn(async () => {
			throw new Error('no route');
		}) as unknown as typeof fetch;
		expect(await checkProof('secret', 'token', 'search', down)).toBe('unchecked');
		const faulty = cloudflare({ success: false, 'error-codes': ['internal-error'] });
		expect(await checkProof('secret', 'token', 'search', faulty)).toBe('unchecked');
		log.mockRestore();
	});

	it('is unchecked when the answer is no verdict', async () => {
		const log = vi.spyOn(console, 'error').mockImplementation(() => {});
		for (const status of [429, 500, 503]) {
			const limited = vi.fn(async () =>
				Response.json({ success: false, errors: [{ code: 1015 }] }, { status })
			) as unknown as typeof fetch;
			expect(await checkProof('secret', 'token', 'search', limited)).toBe('unchecked');
		}
		expect(await checkProof('secret', 'token', 'search', cloudflare(null))).toBe('unchecked');
		expect(await checkProof('secret', 'token', 'search', cloudflare({ errors: [] }))).toBe(
			'unchecked'
		);
		log.mockRestore();
	});

	it('tells an unknown secret from a refusal', async () => {
		for (const code of ['missing-input-secret', 'invalid-input-secret']) {
			const fetcher = cloudflare({ success: false, 'error-codes': [code] });
			expect(await checkProof('secret', 'token', 'search', fetcher)).toBe('unknown-secret');
		}
	});
});

describe('requiredActions', () => {
	it('requires nothing when unset', () => {
		expect(requiredActions(undefined)).toEqual([]);
		expect(requiredActions('')).toEqual([]);
	});

	it('reads a comma-separated list', () => {
		expect(requiredActions('search')).toEqual(['search']);
		expect(requiredActions(' search , ')).toEqual(['search']);
	});

	it('throws on a name that is not an action', () => {
		expect(() => requiredActions('search,join')).toThrow('join');
	});
});
