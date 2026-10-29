import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { extrasolarBase } from '$lib/fetch/extrasolar/files';
import { isExtrasolarObjectId } from '$lib/fetch/extrasolar/ids';
import { minimalSeo } from '$lib/seo/meta';
import { NAV_UNSET, parseNavEnd } from '$lib/state/nav-end';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, url }) => {
	// An end may be unchosen (absent segment or unset marker), but a segment
	// naming one must parse as a body, or the renderer gets an unresolvable id.
	for (const id of [params.from, params.to]) {
		if (id === undefined || id === NAV_UNSET) continue;
		const end = parseNavEnd(id);
		if (!end) error(404, `Unknown body id "${id}"`);
		// A host without an extrasolar export has no star or planet pages.
		if (isExtrasolarObjectId(end.bodyId) && !extrasolarBase()) {
			error(404, 'No extrasolar catalogue');
		}
	}

	if (browser) return { seo: null };

	// A trip has no indexable subject of its own — both ends already have pages,
	// and the route count is the square of the catalogue. Minimal meta only.
	return { seo: minimalSeo(url, url.pathname) };
};
