import { error, json } from '@sveltejs/kit';
import { generateTenantToken } from 'meilisearch/token';
import { env } from '$env/dynamic/private';
import { checkProof, requiredActions } from '$lib/server/turnstile';
import type { RequestHandler } from './$types';

/** A key lasts this long. A visitor makes one proof for each key. */
const TTL_S = 3600;

/** A fault in the settings. The log gets the reason. */
function misconfigured(reason: string): never {
	console.error(reason);
	error(503, 'search is not set up');
}

/**
 * Gives the page a short-lived Meilisearch key, signed with the search key that
 * stays on this server.
 *
 * With `TURNSTILE_SECRET` set, the `proof` in the request is checked with
 * Cloudflare. `TURNSTILE_REQUIRE=search` refuses a request that has no proof
 * that holds. Without it, such a request is logged and gets its key.
 * `TURNSTILE_REQUIRE` without the secret is a fault: no proof can be checked.
 */
export const POST: RequestHandler = async ({ request, fetch }) => {
	const { MEILI_SEARCH_KEY, MEILI_SEARCH_KEY_UID, TURNSTILE_SECRET, TURNSTILE_REQUIRE } = env;
	if (!MEILI_SEARCH_KEY || !MEILI_SEARCH_KEY_UID) {
		misconfigured('MEILI_SEARCH_KEY or MEILI_SEARCH_KEY_UID is unset');
	}
	const required = requiredActions(TURNSTILE_REQUIRE).includes('search');
	if (required && !TURNSTILE_SECRET) misconfigured('TURNSTILE_REQUIRE needs TURNSTILE_SECRET');
	if (TURNSTILE_SECRET) {
		const body: { proof?: unknown } | null = await request.json().catch(() => null);
		const proof = await checkProof(TURNSTILE_SECRET, body?.proof, 'search', fetch);
		if (proof === 'unknown-secret') {
			// With proof required, a wrong secret must not pass for an outage.
			if (required) misconfigured('Cloudflare does not know TURNSTILE_SECRET');
			console.error('Cloudflare does not know TURNSTILE_SECRET');
		}
		// `unchecked` gets its key: an outage at Cloudflare must not stop search.
		const refused = required && (proof === 'absent' || proof === 'refused');
		if (proof !== 'held')
			console.info('no proof of a person', { action: 'search', proof, refused });
		if (refused) error(403, 'unverified');
	}
	const key = await generateTenantToken({
		apiKey: MEILI_SEARCH_KEY,
		apiKeyUid: MEILI_SEARCH_KEY_UID,
		expiresAt: new Date(Date.now() + TTL_S * 1000)
	});
	return json({ key, ttl: TTL_S }, { headers: { 'Cache-Control': 'no-store' } });
};
