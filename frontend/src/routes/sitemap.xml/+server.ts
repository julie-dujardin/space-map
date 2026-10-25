import type { RequestHandler } from './$types';
import { proxySitemap } from '$lib/seo/sitemap';

export const prerender = false;

/** The sitemap index. Its files are `sitemap-<n>.xml`. */
export const GET: RequestHandler = ({ fetch }) => proxySitemap(fetch, 'sitemap.xml');
