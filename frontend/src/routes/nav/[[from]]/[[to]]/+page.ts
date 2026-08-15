import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { minimalSeo } from '$lib/seo/meta';
import type { PageLoad } from './$types';

/** Mirrors parseNavEnd and NAV_UNSET in url.ts (not imported: that module pulls
 *  in client-only `$app/state`). */
const ID_PREFIXES = ['naif-', 'spkid-', 'norad_satcat-', 'probe-', 'extra-'];
const NAV_UNSET = '-';
const FEATURE_INFIX = '-f-';

function isBodyId(value: string): boolean {
	const prefix = ID_PREFIXES.find((p) => value.startsWith(p));
	return prefix !== undefined && Number.isFinite(Number(value.slice(prefix.length)));
}

function isNavEnd(value: string): boolean {
	const cut = value.indexOf(FEATURE_INFIX);
	if (cut === -1) return isBodyId(value);
	const featureId = Number(value.slice(cut + FEATURE_INFIX.length));
	return isBodyId(value.slice(0, cut)) && Number.isInteger(featureId) && featureId > 0;
}

export const load: PageLoad = async ({ params, url }) => {
	// Either end may be unchosen — as an absent segment or as the unset marker —
	// but a segment naming one has to name a body, optionally refined by a place
	// on it, or the renderer is handed an id it can never resolve.
	for (const id of [params.from, params.to]) {
		if (id !== undefined && id !== NAV_UNSET && !isNavEnd(id)) {
			error(404, `Unknown body id "${id}"`);
		}
	}

	if (browser) return { seo: null };

	// A trip has no indexable subject of its own — both ends already have pages,
	// and the route count is the square of the catalogue. Minimal meta only.
	return { seo: minimalSeo('', url.origin, url.pathname) };
};
