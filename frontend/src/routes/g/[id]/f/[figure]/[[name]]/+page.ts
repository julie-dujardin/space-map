import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { extrasolarBase } from '$lib/fetch/extrasolar/files';
import { catalogueSeo, loadFigureSeo } from '$lib/seo/meta';
import { groupHref } from '$lib/state/page-href';
import { figureOfRoute } from '$lib/state/view';
import type { PageLoad } from './$types';

// A route of its own: the feature route's segment is a number, and a body's.
export const load: PageLoad = async ({ params, url }) => {
	// The culture files live in the extrasolar export.
	if (!extrasolarBase()) error(404, 'No extrasolar catalogue');
	const figure = figureOfRoute(params.id, params.figure);
	if (figure === null) error(404, `Unknown figure "${params.id}/f/${params.figure}"`);

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };

	return {
		seo: await catalogueSeo(
			loadFigureSeo(params.id, figure, url),
			url,
			groupHref(params.id, '', figure)
		)
	};
};
