/**
 * Credits page data loader. Fetches the single aggregated `credits.json` and
 * hands it to the component; no Three.js / ContextManager imports here on
 * purpose — this route is deliberately isolated from the 3D map so it works
 * as a plain static page (crawlable, shareable).
 */

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
 * Textures grouped by planetary system. `id`/`name` are null for the
 * standalone bucket (sun-orbiting bodies like Bennu or Ceres that don't
 * belong to any planetary system).
 */
export interface SystemGroup {
	id: string | null;
	name: string | null;
	textures: TextureCredit[];
}

export interface Credits {
	systems: SystemGroup[];
}

export const load = async ({
	fetch
}: {
	fetch: typeof globalThis.fetch;
}): Promise<{ credits: Credits }> => {
	const res = await fetch('/data/v1/credits.json');
	if (!res.ok) throw new Error(`Failed to load credits.json: ${res.status}`);
	const credits = (await res.json()) as Credits;
	return { credits };
};
