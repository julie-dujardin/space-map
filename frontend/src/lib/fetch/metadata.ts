/**
 * Shared loader for `/data/v1/metadata.json`. Memoized — every consumer
 * (chunk prefetcher, Chebyshev store init, object-detail bundle lookup)
 * shares the same fetch.
 */

import type { ChebyshevManifest } from './chebyshev/store';
import { DATA_BASE } from './data-base';
import { dateToJD } from '$lib/format/date';

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
 * Pick the snapshot to render for a (zone, zoom) at simulated time `jd`. For
 * time-segmented zones we choose the snapshot whose date is closest to `jd`
 * — SGP4 only stays accurate ±14d around the TLE epoch, so far-from-now jds
 * (URL-loaded future date, time-warp scrub) need a different snapshot than
 * "today." Returned `time` is the ISO date threaded into the chunk URL; `null`
 * means the flat layout (`elements/{zone}/{zoom}/{part}.*`).
 */
export function selectSnapshot(
	entry: ZoomEntry,
	jd: number
): { stats: ChunkStats; time: string | null } {
	if ('times' in entry) {
		const isoDates = Object.keys(entry.times);
		let best = isoDates[0];
		let bestDist = Math.abs(isoDateToJd(best) - jd);
		for (let i = 1; i < isoDates.length; i++) {
			const d = Math.abs(isoDateToJd(isoDates[i]) - jd);
			if (d < bestDist) {
				best = isoDates[i];
				bestDist = d;
			}
		}
		return { stats: entry.times[best], time: best };
	}
	return { stats: entry, time: null };
}

// Cache the parsed JD for each ISO date so per-frame swap evaluation doesn't
// allocate a Date per snapshot per call. Daily exports anchored to noon UTC
// (the cron time for celestrak fetch) so the midpoint between snapshots is
// midnight UTC — closer to a natural "use yesterday's snap until midnight" UX.
const isoToJdCache = new Map<string, number>();
function isoDateToJd(iso: string): number {
	let jd = isoToJdCache.get(iso);
	if (jd === undefined) {
		jd = dateToJD(new Date(iso + 'T12:00:00Z'));
		isoToJdCache.set(iso, jd);
	}
	return jd;
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
