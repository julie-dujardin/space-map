import { error } from '@sveltejs/kit';
import { BODY_ROUTE_TYPES } from '$lib/state/view';

export const ssr = false;

// 404 unknown type segments instead of coercing them to a `naif-` body.
export function load({ params }) {
	if (!BODY_ROUTE_TYPES.has(params.type)) {
		error(404, `Unknown type segment "${params.type}"`);
	}
}
