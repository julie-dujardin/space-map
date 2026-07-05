import { error } from '@sveltejs/kit';
import { FEATURE_ROUTE_TYPES } from '$lib/state/view';

export const ssr = false;

// Features hang off a body — 404 any non-body type segment.
export function load({ params }) {
	if (!FEATURE_ROUTE_TYPES.has(params.type)) {
		error(404, `Unknown type segment "${params.type}"`);
	}
}
