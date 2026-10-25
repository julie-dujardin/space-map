import { error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { proxySitemap } from '$lib/seo/sitemap';

export const prerender = false;

/** A file of the sitemap index. */
export const GET: RequestHandler = ({ fetch, params }) => {
	if (!/^[1-9]\d*$/.test(params.n)) error(404, 'Not found');
	return proxySitemap(fetch, `sitemap-${params.n}.xml`);
};
