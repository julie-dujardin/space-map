/**
 * Shared loader for `/data/v1/metadata.json`. Memoized — every consumer
 * (chunk prefetcher, Chebyshev store init, object-detail bundle lookup)
 * shares the same fetch.
 */

import type { ChebyshevManifest } from './chebyshev/store';
import { DATA_BASE } from './data-base';

/**
 * Bucket counts for hash-bucketed object detail bundles. `global` is the
 * count for `/data/v1/objects/__global__/{bucket}.json.gz`; each language key
 * gives the bundle count for that language's localized detail dir.
 *
 * The backend picks N at export time so average members-per-bundle hits a
 * fixed K (100 global, 200 localized). Consumers compute
 * `hash(id) % N` to locate the bundle holding a given object.
 */
export type ObjectBundles = {
	global: number;
} & Record<string, number>;

export interface ChunkInfo {
	parts: number;
	object_count: number;
	avg_part_bytes: number;
}

/**
 * Per-zoom metadata. Flat zones expose `parts` directly; time-segmented zones
 * (currently only `earth`) expose a `times` map keyed by ISO date — callers
 * pick the snapshot nearest the simulated time and pass it as `time` to the
 * URL builders.
 */
export type ZoomMetadata = ChunkInfo | { times: Record<string, ChunkInfo> };

export function isTimeSegmented(zoom: ZoomMetadata): zoom is { times: Record<string, ChunkInfo> } {
	return 'times' in zoom;
}

export interface ZoneMetadata {
	zooms: Record<string, ZoomMetadata>;
}

/**
 * Pick the ISO-date snapshot whose date is closest to `date`. Falls back to
 * the only available date when there's just one. Caller must ensure the map
 * is non-empty.
 */
export function pickNearestSnapshot(times: Record<string, unknown>, date: Date): string {
	const target = date.getTime();
	let best: string | null = null;
	let bestDiff = Infinity;
	for (const iso of Object.keys(times)) {
		const diff = Math.abs(new Date(`${iso}T00:00:00Z`).getTime() - target);
		if (diff < bestDiff) {
			bestDiff = diff;
			best = iso;
		}
	}
	return best!;
}

export interface Metadata {
	version: number;
	exported_at: string;
	zones: Record<string, ZoneMetadata>;
	object_bundles: ObjectBundles;
	chebyshev?: ChebyshevManifest;
}

let pending: Promise<Metadata> | null = null;

export function fetchMetadata(): Promise<Metadata> {
	if (pending) return pending;
	pending = fetch(`${DATA_BASE}/v1/metadata.json`).then((r) => {
		if (!r.ok) throw new Error(`Failed to fetch metadata: ${r.status}`);
		return r.json() as Promise<Metadata>;
	});
	return pending;
}

/**
 * Deterministic bucket from an object id. Must mirror `hash_bucket` in
 * `data/src/space_map_data/export/objects/writer.py` — same sha256, same
 * first-4-bytes-big-endian, same modulo.
 */
export async function hashBucket(id: string, nBuckets: number): Promise<number> {
	const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(id));
	return new DataView(digest).getUint32(0, false) % nBuckets;
}
