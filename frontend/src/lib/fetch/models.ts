/**
 * The published model index (`v1/models/index.json`): every curated model
 * bundle beside the Objects it draws. DAMIT lightcurve bundles are left out by
 * the export, so this is the set a reader can be offered.
 *
 * A craft bundle carries its real span here; a shape model carries its true km
 * in its own sidecar (`fetchBundleMeta`) instead, so a size shown for one needs
 * that second fetch.
 */

import { fetchMetadata } from './metadata';
import { versionedUrl } from './data-base';

/** An Object the bundle's mesh is attached to. A bus shared by a fleet lists
 *  every craft flying it, so this runs to the hundreds on the generic buses. */
export interface ModelIndexObject {
	id: string;
	name: string;
	type: string;
}

export interface ModelIndexEntry {
	slug: string;
	/** `shape_model` for a body's measured shape; otherwise the kind of craft
	 *  (`probe`, `earth_sat`, `lander`, `station`, `generic_sat`). */
	kind?: string;
	tiers?: string[];
	/** The model's longest real dimension (m), everything it draws deployed.
	 *  Null on shape models and on craft whose span is not yet measured. */
	scale_meters?: number | null;
	/** The craft body within that span, booms and arrays excluded. */
	body_span_ratio?: number | null;
	/** The mesh's x/y/z extents as fractions of its longest, in the model's own
	 *  frame — what a box drawn around it has to be shaped like. */
	span_ratios?: number[] | null;
	objects: ModelIndexObject[];
}

let cached: Promise<ModelIndexEntry[]> | undefined;

/** Every curated bundle, fetched once per session. */
export function fetchModelIndex(): Promise<ModelIndexEntry[]> {
	cached ??= load();
	return cached;
}

async function load(): Promise<ModelIndexEntry[]> {
	await fetchMetadata(); // the `models` version the URL is stamped with
	const res = await fetch(versionedUrl('/v1/models/index.json', 'models'));
	if (!res.ok) throw new Error(`models/index.json: ${res.status}`);
	const data = (await res.json()) as {
		bundles?: Record<string, Omit<ModelIndexEntry, 'slug'>>;
	};
	return Object.entries(data.bundles ?? {}).map(([slug, bundle]) => ({
		...bundle,
		slug,
		objects: bundle.objects ?? []
	}));
}
