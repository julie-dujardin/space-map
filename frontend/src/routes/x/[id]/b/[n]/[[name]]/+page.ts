import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { planetOfObjectId } from '$lib/fetch/extrasolar/ids';
import { extrasolarBase } from '$lib/fetch/extrasolar/files';
import { extrasolarSeo, loadPlanetSeo } from '$lib/seo/meta';
import { planetHref } from '$lib/state/page-href';
import { planetIdOfRoute } from '$lib/state/view';
import type { PageLoad } from './$types';

// A route of its own: a nested `[type]/[id]/b/[n]` would also match `/b/399/b/1`.
export const load: PageLoad = async ({ params, url }) => {
	// A host without an extrasolar export has no planet pages.
	if (!extrasolarBase()) error(404, 'No extrasolar catalogue');
	const objectId = planetIdOfRoute(params.id, params.n);
	if (objectId === null) error(404, `Unknown planet "${params.id}/b/${params.n}"`);

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };

	const { host, n } = planetOfObjectId(objectId)!;
	return { seo: await extrasolarSeo(loadPlanetSeo(host, n, url), url, planetHref(host, n, '')) };
};
