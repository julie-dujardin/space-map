import { error } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { bodyHref, groupHref } from '$lib/state/page-href';
import { BODY_ROUTE_TYPES, UrlType, objectIdOfRoute } from '$lib/state/view';
import { catalogueSeo, loadGroupSeo, loadObjectSeo } from '$lib/seo/meta';
import type { PageLoad } from './$types';

export const load: PageLoad = async ({ params, url }) => {
	const { type, id } = params;
	// 404 unknown type segments instead of coercing them to a `naif-` body.
	if (!BODY_ROUTE_TYPES.has(type)) error(404, `Unknown type segment "${type}"`);
	// Groups (/g/<slug>) live in their own bundle; the [id] slot holds the slug.
	const isGroup = type === UrlType.Group;
	const objectId = isGroup ? null : objectIdOfRoute(type, id);
	if (!isGroup && objectId === null) error(404, `Unknown id "${id}"`);

	// Meta matters only for the server-rendered document; client navigations let
	// MapPage own the head, so skip the fetch there.
	if (browser) return { seo: null };

	const seo =
		objectId === null
			? catalogueSeo(loadGroupSeo(id, url), url, groupHref(id, ''))
			: catalogueSeo(loadObjectSeo(objectId, url), url, bodyHref(objectId, ''));
	return { seo: await seo };
};
