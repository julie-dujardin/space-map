/**
 * Credits page data loader. Fetches the single aggregated `credits.json` and
 * hands it to the component; no Three.js / ContextManager imports here on
 * purpose — this route is deliberately isolated from the 3D map so it works
 * as a plain static page (crawlable, shareable).
 */

import { DATA_BASE } from '$lib/fetch/data-base';

export interface TextureCredit {
	body_id: string;
	name: string;
	source: string;
	organisation: string;
	type: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body planetary-ring credit — sibling to {@link TextureCredit} minus
 * the `type` field (ring profiles are radial-only, the array name is the
 * disambiguator).
 */
export interface RingCredit {
	body_id: string;
	name: string;
	source: string;
	organisation: string;
	attribution?: string;
	description?: string;
}

/**
 * Credit-worthy bodies grouped by planetary system. `id`/`name` are null for
 * the standalone bucket (sun-orbiting bodies like Bennu or Ceres that don't
 * belong to any planetary system). `textures` and `rings` are both optional;
 * a system bucket lands here as soon as it has at least one of either.
 */
export interface SystemGroup {
	id: string | null;
	name: string | null;
	textures?: TextureCredit[];
	rings?: RingCredit[];
}

export interface Credits {
	systems: SystemGroup[];
}

export const load = async ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): Promise<{ credits: Credits }> => {
	const res = await fetch(`${DATA_BASE}/v1/credits.json`);
	if (!res.ok) throw new Error(`Failed to load credits.json: ${res.status}`);
	const credits = (await res.json()) as Credits;
	return { credits };
};
