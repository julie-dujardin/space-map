/**
 * Credits page data loader. Fetches the single aggregated `credits.json` and
 * hands it to the component; no Three.js / ContextManager imports here on
 * purpose — this route is deliberately isolated from the 3D map so it works
 * as a plain static page (crawlable, shareable).
 */

import { DATA_BASE } from '$lib/fetch/data-base';

// No SEO value, and its loader fetches `/data` (which collides with the
// [type]/[id] route under SSR), so this stays client-rendered.
export const ssr = false;

export interface TextureCredit {
	body_id: string;
	name: string;
	source: string;
	organisation: string;
	license?: string;
	type: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body planetary-ring credit: sibling to {@link TextureCredit} minus
 * the `type` field (ring profiles are radial-only, the array name is the
 * disambiguator).
 */
export interface RingCredit {
	body_id: string;
	name: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body cloud-overlay credit: same shape as {@link RingCredit}; the
 * array name disambiguates it from surface imagery.
 */
export interface CloudCredit {
	body_id: string;
	name: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body night-lights credit: same shape as {@link CloudCredit}; the
 * array name disambiguates it from surface imagery.
 */
export interface NightCredit {
	body_id: string;
	name: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Per-body displacement/topography credit: same shape as {@link NightCredit};
 * the array name disambiguates it from surface imagery.
 */
export interface DisplacementCredit {
	body_id: string;
	name: string;
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/**
 * Credit-worthy bodies grouped by planetary system. `id`/`name` are null for
 * the standalone bucket (sun-orbiting bodies like Bennu or Ceres that don't
 * belong to any planetary system). `textures`, `rings`, `clouds`, `night`,
 * and `displacement` are all optional; a system bucket lands here as soon as
 * it has at least one.
 */
export interface SystemGroup {
	id: string | null;
	name: string | null;
	textures?: TextureCredit[];
	rings?: RingCredit[];
	clouds?: CloudCredit[];
	night?: NightCredit[];
	displacement?: DisplacementCredit[];
}

/**
 * Whole-sky cubemap backdrop credit. Sits at the top level alongside `systems`
 * because the skybox has no host body: it's a single global asset.
 */
export interface SkyboxCredit {
	source: string;
	organisation: string;
	license?: string;
	attribution?: string;
	description?: string;
}

/** Entry in the orbital-credits section; `id` matches `global.ephemeris_source`. */
export interface EphemerisArchive {
	id: string;
	source: string;
	organisation: string;
}

/**
 * One row in the 3D-models section — a catalog name + its landing page.
 * Per-spacecraft model credits aren't shipped (the catalog license covers
 * every model from that source); this is the catalog roll-up emitted by
 * the exporter only when at least one ingested model came from it.
 */
export interface ModelCatalog {
	name: string;
	url: string;
	license?: string;
}

/**
 * One literature source behind a hand-curated constant — an atmosphere, a
 * ring, a temperature, an interior model (see the `references.py` beside each
 * in data/src/space_map_data/constants/). English-only like the rest of the
 * credits payload.
 */
export interface Reference {
	title: string;
	url: string;
	contribution: string;
}

export interface Credits {
	systems: SystemGroup[];
	ephemeris_archives: EphemerisArchive[];
	atmosphere_references?: Reference[];
	ring_references?: Reference[];
	temperature_references?: Reference[];
	interior_references?: Reference[];
	activity_references?: Reference[];
	radiation_references?: Reference[];
	spacecraft_references?: Reference[];
	models?: ModelCatalog[];
	skybox?: SkyboxCredit;
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
