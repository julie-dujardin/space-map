import { resolve } from '$app/paths';
import type { PanoramaEntry } from '$lib/fetch/objects/object-data';
import { panoramaAt } from '$lib/panorama/traverse';
import { urlTypeFromId, urlTypeToIdPrefix } from './view';

/** `/view/<type>/<id>` for the body, plus the panorama when one is named. */
export function panoramaHref(bodyId: string, entry?: PanoramaEntry): string {
	const type = urlTypeFromId(bodyId);
	const numericId = bodyId.slice(`${urlTypeToIdPrefix(type)}-`.length);
	const path = resolve('/view/[type]/[id]', { type, id: numericId });
	return entry ? `${path}?at=${encodeURIComponent(panoramaAt(entry))}` : path;
}
