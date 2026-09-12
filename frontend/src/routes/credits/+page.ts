/**
 * Credits page data loader. No Three.js / ContextManager imports on purpose —
 * this route stays a plain static page (crawlable, shareable), independent of the 3D map.
 */

import * as m from '$lib/paraglide/messages.js';
import { dataBase } from '$lib/fetch/data-base';

// No SEO value, and its loader fetches `/data` (which collides with the
// [type]/[id] route under SSR), so this stays client-rendered.
export const ssr = false;

/** One credited work behind a body's imagery. The layer it belongs to is the
 *  array it sits in — `textures`, `rings`, … — matching `export/credits.py`. */
export interface BodyCredit {
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
 * the standalone bucket (bodies with no planetary system, e.g. Bennu, Ceres).
 */
export interface SystemGroup {
	id: string | null;
	name: string | null;
	textures?: BodyCredit[];
	rings?: BodyCredit[];
	clouds?: BodyCredit[];
	night?: BodyCredit[];
	specular?: BodyCredit[];
	displacement?: BodyCredit[];
}

/** Whole-sky cubemap backdrop credit; sits alongside `systems` since it has no host body. */
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
 * One row in the 3D-models section: a catalog name + landing page.
 * Per-spacecraft credits aren't shipped — the catalog license covers every model from that source.
 */
export interface ModelCatalog {
	name: string;
	url: string;
	license?: string;
}

/** One literature source behind a hand-curated constant (see `references.py` beside each in data/src/space_map_data/constants/). */
export interface Reference {
	title: string;
	url: string;
	contribution: string;
}

/** Wire field names of the reference bundles, as `export/credits.py` writes them. */
export type ReferenceSection =
	| 'atmosphere_references'
	| 'ring_references'
	| 'interior_references'
	| 'activity_references'
	| 'temperature_references'
	| 'radiation_references'
	| 'spacecraft_references';

/**
 * The reference sections, declared once: array order is render order on
 * /credits, so a new bundle needs an entry here and nothing in the template.
 */
export const REFERENCE_SECTIONS = [
	{ key: 'atmosphere_references', label: m.attribution_section_atmospheres },
	{ key: 'ring_references', label: m.attribution_section_rings },
	{ key: 'interior_references', label: m.attribution_section_interiors },
	{ key: 'activity_references', label: m.attribution_section_activity },
	{ key: 'temperature_references', label: m.attribution_section_temperatures },
	{ key: 'radiation_references', label: m.attribution_section_radiation },
	{ key: 'spacecraft_references', label: m.attribution_section_spacecraft }
] as const satisfies readonly { key: ReferenceSection; label: () => string }[];

export interface Credits extends Partial<Record<ReferenceSection, Reference[]>> {
	systems: SystemGroup[];
	ephemeris_archives: EphemerisArchive[];
	models?: ModelCatalog[];
	skybox?: SkyboxCredit;
}

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
