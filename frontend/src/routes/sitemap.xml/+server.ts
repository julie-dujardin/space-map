import type { RequestHandler } from './$types';
import { DATA_BASE } from '$lib/fetch/data-base';

// Serve the export-built sitemap from the app origin so every <loc> host matches
// the sitemap's own — no Search Console cross-host verification needed. The file
// lands on the data CDN with each export; until then this 502s.
export const prerender = false;

export const GET: RequestHandler = async ({ fetch }) => {
	const upstream = await fetch(`${DATA_BASE}/v1/seo/sitemap.xml`);
	if (!upstream.ok) {
		return new Response('sitemap unavailable', { status: 502 });
	}
	return new Response(upstream.body, {
		headers: {
			'content-type': 'application/xml; charset=utf-8',
			// Sitemap only changes on export; let the edge hold it a day.
			'cache-control': 'public, max-age=3600, s-maxage=86400'
		}
	});
};
