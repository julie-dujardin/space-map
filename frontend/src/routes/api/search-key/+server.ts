import { error, json } from '@sveltejs/kit';
import { generateTenantToken } from 'meilisearch/token';
import { env } from '$env/dynamic/private';
import type { RequestHandler } from './$types';

/** A key lasts this long. */
const TTL_S = 3600;

/** A fault in the settings. The log gets the reason. */
function misconfigured(reason: string): never {
	console.error(reason);
	error(503, 'search is not set up');
}

/**
 * Gives the page a short-lived Meilisearch key, signed with the search key that
 * stays on this server.
 */
export const POST: RequestHandler = async () => {
	const { MEILI_SEARCH_KEY, MEILI_SEARCH_KEY_UID } = env;
	if (!MEILI_SEARCH_KEY || !MEILI_SEARCH_KEY_UID) {
		misconfigured('MEILI_SEARCH_KEY or MEILI_SEARCH_KEY_UID is unset');
	}
	const key = await generateTenantToken({
		apiKey: MEILI_SEARCH_KEY,
		apiKeyUid: MEILI_SEARCH_KEY_UID,
		expiresAt: new Date(Date.now() + TTL_S * 1000)
	});
	return json({ key, ttl: TTL_S }, { headers: { 'Cache-Control': 'no-store' } });
};
