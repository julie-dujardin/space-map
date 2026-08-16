import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { minimalSeo } from '$lib/seo/meta';
import { NAV_UNSET, parseNavEnd } from '$lib/state/nav-end';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, url }) => {
	// An end may be unchosen (absent segment or unset marker), but a segment
	// naming one must parse as a body, or the renderer gets an unresolvable id.
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
