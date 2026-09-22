/**
 * Credits page data loader. No Three.js / ContextManager imports on purpose —
 * this route stays a plain static page (crawlable, shareable), independent of the 3D map.
 */

import { dataBase } from '$lib/fetch/data-base';
import type { Credits } from '$lib/credits/credits-payload';

// No SEO value, and its loader fetches `/data` (which collides with the
// [type]/[id] route under SSR), so this stays client-rendered.
export const ssr = false;

// The payload is handed over unresolved: the page draws its frame the moment
// the row is clicked and fills in when the JSON lands.
export const load = ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): { credits: Promise<Credits> } => {
	const credits = (async () => {
		const res = await fetch(`${dataBase()}/v1/credits.json`);
		if (!res.ok) throw new Error(`Failed to load credits.json: ${res.status}`);
		return (await res.json()) as Credits;
	})();
	return { credits };
};
