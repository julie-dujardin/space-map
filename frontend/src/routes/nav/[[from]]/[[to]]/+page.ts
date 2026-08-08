import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { minimalSeo } from '$lib/seo/meta';
import type { PageLoad } from './$types';

/** Mirrors isBodyId in url.ts (not imported: that module pulls in client-only
 *  `$app/state`). */
const ID_PREFIXES = ['naif-', 'spkid-', 'norad_satcat-', 'probe-', 'extra-'];

function isBodyId(value: string): boolean {
	const prefix = ID_PREFIXES.find((p) => value.startsWith(p));
	return prefix !== undefined && Number.isFinite(Number(value.slice(prefix.length)));
}

export const load: PageLoad = async ({ params, url }) => {
	// Both ends are optional — bare /nav is the empty form — but a segment that is
	// present has to name a body, or the renderer is handed an id it can never
	// resolve.
	for (const id of [params.from, params.to]) {
		if (id !== undefined && !isBodyId(id)) error(404, `Unknown body id "${id}"`);
	}

	if (browser) return { seo: null };

	// A trip has no indexable subject of its own — both ends already have pages,
	// and the route count is the square of the catalogue. Minimal meta only.
	return { seo: minimalSeo('', url.origin, url.pathname) };
};
