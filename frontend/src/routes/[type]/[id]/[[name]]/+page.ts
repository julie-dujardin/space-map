import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { bodyHref, groupHref } from '$lib/state/page-href';
import { BODY_ROUTE_TYPES, UrlType, objectIdOfRoute } from '$lib/state/view';
import {
	catalogueSeo,
	extrasolarSeo,
	loadGroupSeo,
	loadObjectSeo,
	loadStarSeo
} from '$lib/seo/meta';
import { extrasolarBase } from '$lib/fetch/extrasolar/files';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, url }) => {
	const { type, id } = params;
	// 404 unknown type segments instead of coercing them to a `naif-` body.
	if (!BODY_ROUTE_TYPES.has(type)) error(404, `Unknown type segment "${type}"`);
	// A host without an extrasolar export has no star pages.
	if (type === UrlType.Extrasolar && !extrasolarBase()) error(404, 'No extrasolar catalogue');
	// Groups (/g/<slug>) live in their own bundle; the [id] slot holds the slug.
	const isGroup = type === UrlType.Group;
	const objectId = isGroup ? null : objectIdOfRoute(type, id);
	if (!isGroup && objectId === null) error(404, `Unknown id "${id}"`);

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };

	if (type === UrlType.Extrasolar) {
		return { seo: await extrasolarSeo(loadStarSeo(id, url), url, bodyHref(objectId!, '')) };
	}
	const seo =
		objectId === null
			? catalogueSeo(loadGroupSeo(id, url), url, groupHref(id, ''))
			: catalogueSeo(loadObjectSeo(objectId, url), url, bodyHref(objectId, ''));
	return { seo: await seo };
};
