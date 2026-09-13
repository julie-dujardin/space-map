/**
 * Credits page data loader. No Three.js / ContextManager imports on purpose —
 * this route stays a plain static page (crawlable, shareable), independent of the 3D map.
 */

import { dataBase } from '$lib/fetch/data-base';
import type { Credits } from '$lib/credits/credits-payload';

// No SEO value, and its loader fetches `/data` (which collides with the
// [type]/[id] route under SSR), so this stays client-rendered.
export const ssr = false;

export const load = async ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): Promise<{ credits: Credits }> => {
	const res = await fetch(`${dataBase()}/v1/credits.json`);
	if (!res.ok) throw new Error(`Failed to load credits.json: ${res.status}`);
	const credits = (await res.json()) as Credits;
	return { credits };
};
