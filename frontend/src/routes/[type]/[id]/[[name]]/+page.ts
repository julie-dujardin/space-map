import { error, redirect } from '@sveltejs/kit';
import { browser } from '$app/environment';
import { bodyHref, groupHref } from '$lib/state/page-href';
import { BODY_ROUTE_TYPES, UrlType, objectIdOfRoute } from '$lib/state/view';
import {
	catalogueSeo,
	loadGroupSeo,
	loadObjectSeo,
	loadStarSeo,
	minimalSeo,
	type SeoMeta,
	type StarPage
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

	if (type === UrlType.Extrasolar) return { seo: await starSeo(id, url, objectId!) };
	const seo =
		objectId === null
			? catalogueSeo(loadGroupSeo(id, url), url, groupHref(id, ''))
			: catalogueSeo(loadObjectSeo(objectId, url), url, bodyHref(objectId, ''));
	return { seo: await seo };
};

/** A star page's meta: a 404 for an ID with no live row, a permanent redirect
 *  for an alias, and bare meta when the export cannot be read. */
async function starSeo(id: string, url: URL, objectId: string): Promise<SeoMeta> {
	let page: StarPage | null;
	try {
		page = await loadStarSeo(id, url);
	} catch (e) {
		console.warn(`[seo] ${url.pathname}: extrasolar export not readable, bare meta:`, e);
		return minimalSeo(url, bodyHref(objectId, ''));
	}
	if (!page) error(404, 'Not found');
	if (page.kind === 'alias') redirect(301, page.location);
	return page.seo;
}
