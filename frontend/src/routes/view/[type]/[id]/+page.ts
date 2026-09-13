import { error } from '@sveltejs/kit';
import { BODY_ROUTE_TYPES, UrlType, urlTypeToIdPrefix } from '$lib/state/view';
import type { PageLoad } from './$types';

// WebGL-only page with nothing for a crawler yet; the object page carries the
// body's metadata.
export const ssr = false;

export const load: PageLoad = ({ params }) => {
	if (!BODY_ROUTE_TYPES.has(params.type) || params.type === UrlType.Group) {
		error(404, `Unknown type segment "${params.type}"`);
	}
	return { bodyId: `${urlTypeToIdPrefix(params.type)}-${params.id}` };
};
