/**
 * IAU quadrangle index — one small file covering every mapped body
 * (Mercury, Venus, Mars, the Moon). Written by
 * `data/src/space_map_data/export/nomenclature/quadrangles.py`.
 *
 * Fetched once and memoized: the Surface tab's hero draws these boxes over the
 * body's map texture, and a selected box narrows the feature list.
 */

import { fetchGzipBundle } from '$lib/fetch/bundle-cache';
import { versionedUrl } from '$lib/fetch/data-base';

/** One chart area. Longitudes are east-positive; a cell straddling the prime
 *  meridian has `lon_min + lon_span > 360`. */
export interface Quadrangle {
	code: string;
	/** IAU chart name ("Mare Boreum", "Copernicus"); falls back to the code. */
	name: string;
	/** Renderable features inside it. */
	n: number;
	lat_min: number;
	lat_max: number;
	lon_min: number;
	lon_span: number;
}

export interface BodyQuadrangles {
	quads: Quadrangle[];
	/** feature_id → code, for the few features the gazetteer files against the
	 *  neighbouring cell. Unused here — the search index applies them. */
	overrides: Record<string, string>;
}

/** A body's quadrangles, or null when it isn't on a mapped grid. */
export async function fetchBodyQuadrangles(bodyId: string): Promise<Quadrangle[] | null> {
	const all = await fetchGzipBundle<BodyQuadrangles>(
		versionedUrl('/v1/nomenclature/quadrangles.json.gz', 'nomenclature')
	);
	return all[bodyId]?.quads ?? null;
}
