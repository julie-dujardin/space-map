import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { BODY_ROUTE_TYPES } from '$lib/state/view';
import { loadGroupSeo, loadObjectSeo, minimalSeo } from '$lib/seo/meta';
import type { PageLoad } from './$types';

// URL type segment → object id prefix. Mirrors urlTypeToIdPrefix in url.ts (not
// imported: that module pulls in client-only $app/state).
const TYPE_TO_PREFIX: Record<string, string> = {
	b: 'naif',
	s: 'spkid',
	e: 'norad_satcat',
	p: 'probe',
	u: 'extra'
};

export const load: PageLoad = async ({ params, url }) => {
	// 404 unknown type segments instead of coercing them to a `naif-` body.
	if (!BODY_ROUTE_TYPES.has(params.type)) {
		error(404, `Unknown type segment "${params.type}"`);
	}

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };

	const { type, id, name } = params;
	const decodedName = name ? decodeURIComponent(name) : '';
	const path = url.pathname;

	// Groups (/g/<slug>) live in their own bundle; the [id] slot holds the slug.
	if (type === 'g') {
		const seo = await loadGroupSeo(id, url.origin, path);
		return { seo: seo ?? minimalSeo(decodedName || id, url.origin, path) };
	}

	const prefix = TYPE_TO_PREFIX[type];
	if (!prefix) return { seo: minimalSeo(decodedName, url.origin, path) };

	const seo = await loadObjectSeo(`${prefix}-${id}`, url.origin, path);
	return { seo: seo ?? minimalSeo(decodedName, url.origin, path) };
};
