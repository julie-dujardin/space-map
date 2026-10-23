import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { featureHref } from '$lib/state/page-href';
import { FEATURE_ROUTE_TYPES, featureIdOfRoute, objectIdOfRoute } from '$lib/state/view';
import { catalogueSeo, loadFeatureSeo } from '$lib/seo/meta';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, url }) => {
	// Features hang off a body: 404 a group, a star or any other type segment.
	const bodyId = FEATURE_ROUTE_TYPES.has(params.type)
		? objectIdOfRoute(params.type, params.id)
		: null;
	if (bodyId === null) error(404, `Unknown body "/${params.type}/${params.id}"`);
	const featureId = featureIdOfRoute(params.featureId);
	if (featureId === null) error(404, `Unknown feature id "${params.featureId}"`);

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };

	return {
		seo: await catalogueSeo(
			loadFeatureSeo(bodyId, featureId, url),
			url,
			featureHref(bodyId, featureId, '')
		)
	};
};
