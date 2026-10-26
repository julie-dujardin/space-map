/**
 * Query-less paths of the catalogue's pages.
 *
 * The name segment tells a reader what a link opens, and nothing reads it
 * back: a page takes its subject from the ids. Apart from the URL codec, which
 * reads `$app/state`, so that the server builds a page's canonical link from
 * the same functions.
 */

import { resolve } from '$app/paths';
import type { SearchHit } from '$lib/search/client';
import { planetOfObjectId } from '$lib/fetch/extrasolar/ids';
import { UrlType, urlTypeFromId, urlTypeToIdPrefix } from './view';

function nameSegment(name: string): string | undefined {
	return name ? encodeURIComponent(name) : undefined;
}

/** The type and id segments of a body's routes. */
function bodySegments(id: string): { type: UrlType; id: string } {
	const type = urlTypeFromId(id);
	return { type, id: id.slice(`${urlTypeToIdPrefix(type)}-`.length) };
}

/** A body's page: `/<type>/<id>/<name>`, or a planet's page for a planet id. */
export function bodyHref(id: string, name: string): string {
	const planet = planetOfObjectId(id);
	if (planet) return planetHref(planet.host, planet.n, name);
	return resolve('/[type]/[id]/[[name]]', { ...bodySegments(id), name: nameSegment(name) });
}

/** A planet's page: `/x/<host>/b/<n>/<name>`. */
export function planetHref(host: number, n: number, name: string): string {
	return resolve('/x/[id]/b/[n]/[[name]]', {
		id: String(host),
		n: String(n),
		name: nameSegment(name)
	});
}

/** A group's page: `/g/<slug>/<name>`, opening on the group's anchor. */
export function groupHref(slug: string, name: string): string {
	return resolve('/[type]/[id]/[[name]]', {
		type: UrlType.Group,
		id: slug,
		name: nameSegment(name)
	});
}

/** A surface feature's page: `/<type>/<id>/f/<featureId>/<name>`. */
export function featureHref(bodyId: string, featureId: number, name: string): string {
	return resolve('/[type]/[id]/f/[featureId]/[[name]]', {
		...bodySegments(bodyId),
		featureId: String(featureId),
		name: nameSegment(name)
	});
}

/** The page a search hit opens. A pad has no page of its own, so the site that
 *  holds it stands in. */
export function searchHitHref(hit: SearchHit, name: string): string {
	if (hit.kind === 'feature') return featureHref(hit.body_id, hit.feature_id, name);
	if (hit.kind === 'group') return groupHref(hit.slug, name);
	if (hit.kind === 'pad') return groupHref(hit.site_slug, hit.site_name);
	return bodyHref(hit.id, name);
}
