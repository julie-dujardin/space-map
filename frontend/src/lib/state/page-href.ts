/**
 * Query-less paths of the catalogue's pages.
 *
 * The name segment tells a reader what a link opens, and nothing reads it
 * back: a page takes its subject from the ids. Apart from the URL codec, which
 * reads `$app/state`, so that the server builds a page's canonical link from
 * the same functions.
 */

import { resolve } from '$app/paths';
import { UrlType, urlTypeFromId, urlTypeToIdPrefix } from './view';

function nameSegment(name: string): string | undefined {
	return name ? encodeURIComponent(name) : undefined;
}

/** The type and id segments of a body's routes. */
function bodySegments(id: string): { type: UrlType; id: string } {
	const type = urlTypeFromId(id);
	return { type, id: id.slice(`${urlTypeToIdPrefix(type)}-`.length) };
}

/** A body's page: `/<type>/<id>/<name>`. */
export function bodyHref(id: string, name: string): string {
	return resolve('/[type]/[id]/[[name]]', { ...bodySegments(id), name: nameSegment(name) });
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
