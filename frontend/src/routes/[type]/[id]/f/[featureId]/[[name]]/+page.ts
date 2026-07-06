import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { FEATURE_ROUTE_TYPES } from '$lib/state/view';
import { minimalSeo } from '$lib/seo/meta';
import type { PageLoad } from './$types';

export const load: PageLoad = ({ params, url }) => {
	// Features hang off a body — 404 any non-body type segment.
	if (!FEATURE_ROUTE_TYPES.has(params.type)) {
		error(404, `Unknown type segment "${params.type}"`);
	}

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };
	const name = params.name ? decodeURIComponent(params.name) : '';
	return { seo: minimalSeo(name, url.origin, url.pathname) };
};
