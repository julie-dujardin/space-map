/**
 * Status page data loader. Like /credits, a plain static page with no
 * Three.js / ContextManager imports — it reads one JSON and renders it.
 */

import { dataBase } from '$lib/fetch/data-base';
import type { Status } from '$lib/status/status-payload';

// No SEO value, and its loader fetches `/data` (which collides with the
// [type]/[id] route under SSR), so this stays client-rendered.
export const ssr = false;

// The payload is handed over unresolved: the page draws its frame the moment
// the row is clicked and fills in when the JSON lands.
export const load = ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): { status: Promise<Status> } => {
	const status = (async () => {
		const res = await fetch(`${dataBase()}/v1/status.json`);
		if (!res.ok) throw new Error(`Failed to load status.json: ${res.status}`);
		return (await res.json()) as Status;
	})();
	return { status };
};
