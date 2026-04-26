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

export interface ChunkStats {
	parts: number;
	object_count: number;
	avg_part_bytes: number;
}

/**
 * Per-zoom entry in the metadata. Most zones ship a single snapshot — the
 * flat `ChunkStats` shape — but time-segmented zones (currently only `earth`,
 * one snapshot per CelesTrak day-dir) ship a `times` map keyed by ISO date.
 */
export type ZoomEntry = ChunkStats | { times: Record<string, ChunkStats> };

export interface ZoneMetadata {
	zooms: Record<string, ZoomEntry>;
}

/**
 * Pick the snapshot to render for a (zone, zoom). For time-segmented zones we
 * hardcode the most recent snapshot for now — the SGP4 propagator only stays
 * accurate ±14d around the chunk's `start_jd`/`end_jd`, so picking a snapshot
 * close to the user's simulated time is a follow-up. Returned `time` is the
 * ISO date threaded into the chunk URL; `null` means the flat layout
 * (`elements/{zone}/{zoom}/{part}.*`).
 */
export function selectSnapshot(entry: ZoomEntry): { stats: ChunkStats; time: string | null } {
	if ('times' in entry) {
		const isoDates = Object.keys(entry.times).sort();
		const latest = isoDates[isoDates.length - 1];
		return { stats: entry.times[latest], time: latest };
	}
	return { stats: entry, time: null };
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
