/**
 * Status page data loader. Like /credits, a plain static page with no
 * Three.js / ContextManager imports — it reads one JSON and renders it.
 */

import { dataBase } from '$lib/fetch/data-base';
import type { Status } from '$lib/status/status-payload';

// No SEO value, and its loader fetches `/data` (which collides with the
// [type]/[id] route under SSR), so this stays client-rendered.
export const ssr = false;

export const load = async ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): Promise<{ status: Status }> => {
	const res = await fetch(`${dataBase()}/v1/status.json`);
	if (!res.ok) throw new Error(`Failed to load status.json: ${res.status}`);
	const status = (await res.json()) as Status;
	return { status };
};
