import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { minimalSeo } from '$lib/seo/meta';
import { NAV_UNSET, parseNavEnd } from '$lib/state/nav-end';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, url }) => {
	// Either end may be unchosen — as an absent segment or as the unset marker —
	// but a segment naming one has to name a body, optionally refined by a place
	// on it, or the renderer is handed an id it can never resolve. The grammar is
	// the parser's own, so a new shape of end cannot 404 on the way in.
	for (const id of [params.from, params.to]) {
		if (id !== undefined && id !== NAV_UNSET && !parseNavEnd(id)) {
			error(404, `Unknown body id "${id}"`);
		}
	}

	if (browser) return { seo: null };

	// A trip has no indexable subject of its own — both ends already have pages,
	// and the route count is the square of the catalogue. Minimal meta only.
	return { seo: minimalSeo('', url.origin, url.pathname) };
};
