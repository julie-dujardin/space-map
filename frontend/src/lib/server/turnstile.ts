/** Proof that a person is at the page: a Turnstile token, checked with Cloudflare. */

const SITEVERIFY = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
/** Cloudflare makes no longer token. */
const MAX_TOKEN_CHARS = 2048;
const TIMEOUT_MS = 3000;
const UNKNOWN_SECRET = ['missing-input-secret', 'invalid-input-secret'];

/** What can need proof. The page gives Cloudflare the same name. */
const ACTIONS = ['search'] as const;
export type Action = (typeof ACTIONS)[number];

/**
 * - `held`: Cloudflare vouches for the token.
 * - `absent`: no token came.
 * - `refused`: made up, expired, used before, or made for another action.
 * - `unchecked`: Cloudflare gave no answer.
 * - `unknown-secret`: Cloudflare does not know the secret of this server.
 */
export type Proof = 'held' | 'absent' | 'refused' | 'unchecked' | 'unknown-secret';

interface Verdict {
	success: boolean;
	'error-codes'?: string[];
	/** Empty for the test keys of Cloudflare. */
	action?: string;
}

export async function checkProof(
	secret: string,
	token: unknown,
	action: Action,
	fetcher: typeof fetch
): Promise<Proof> {
	if (typeof token !== 'string' || !token) return 'absent';
	if (token.length > MAX_TOKEN_CHARS) return 'refused';
	let verdict: Verdict | null;
	try {
		const answer = await fetcher(SITEVERIFY, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ secret, response: token }),
			signal: AbortSignal.timeout(TIMEOUT_MS)
		});
		// A rate limit or a server fault is about Cloudflare, not the visitor.
		if (answer.status === 429 || answer.status >= 500) throw new Error(`HTTP ${answer.status}`);
		verdict = await answer.json();
		if (typeof verdict?.success !== 'boolean') throw new Error('not a verdict');
	} catch (error) {
		console.error('turnstile did not answer', error);
		return 'unchecked';
	}
	if (verdict.success) return verdict.action && verdict.action !== action ? 'refused' : 'held';
	const codes = verdict['error-codes'] ?? [];
	if (codes.some((code) => UNKNOWN_SECRET.includes(code))) return 'unknown-secret';
	// A fault at Cloudflare says nothing about the visitor.
	if (codes.includes('internal-error')) return 'unchecked';
	return 'refused';
}

/** The actions that `TURNSTILE_REQUIRE` names, comma-separated. */
export function requiredActions(list: string | undefined): Action[] {
	const names = (list ?? '')
		.split(',')
		.map((name) => name.trim())
		.filter(Boolean);
	for (const name of names) {
		if (!ACTIONS.includes(name as Action)) {
			throw new Error(`TURNSTILE_REQUIRE names "${name}". It can name: ${ACTIONS.join(', ')}`);
		}
	}
	return names as Action[];
}
