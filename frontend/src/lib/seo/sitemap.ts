import { dataBase } from '$lib/fetch/data-base';

/**
 * A file of the export-built sitemap, served from the app origin so every
 * <loc> host matches the sitemap's own. Search Console then needs no
 * cross-host verification.
 */
export async function proxySitemap(
	fetch: typeof globalThis.fetch,
	file: string
): Promise<Response> {
	const upstream = await fetch(`${dataBase()}/v1/seo/${file}`);
	if (upstream.status === 404) return new Response('not found', { status: 404 });
	if (!upstream.ok) return new Response('sitemap unavailable', { status: 502 });
	return new Response(upstream.body, {
		headers: {
			'content-type': 'application/xml; charset=utf-8',
			// The sitemap changes only on export, so the edge holds it a day.
			'cache-control': 'public, max-age=3600, s-maxage=86400'
		}
	});
}
