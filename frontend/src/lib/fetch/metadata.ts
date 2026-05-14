/**
 * Shared loader for `/data/v1/metadata.json`. Memoized — every consumer
 * (chunk prefetcher, Chebyshev store init, object-detail bundle lookup)
 * shares the same fetch.
 */

import type { ChebyshevZoneParams } from './position/chebyshev/store';
import type { ProbeZoneParams } from './position/probes/store';
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

/** Static parted zone: `position/{zone}/{zoom}/{part}.bin.gz`. */
export interface PartedZoom {
	shape: 'parted';
	parts: number;
}

/** Time-chunked + parted, ISO-date label (currently `earth`):
 *  `position/{zone}/{zoom}/{YYYY-MM-DD}/{part}.bin.gz`. */
export interface DateSegmentedZoom {
	shape: 'chunked-parted';
	label: 'date';
	start_date: string;
	end_date: string;
	parts: number;
}

/** Time-chunked + parted, integer chunk-idx label (currently `moons`):
 *  `position/{zone}/{zoom}/{chunk_idx}/{part}.bin.gz`. */
export interface ChunkIndexedZoom {
	shape: 'chunked-parted';
	label: 'index';
	chunks: number;
	chunk_years: number;
	start_jd: number;
	parts: number;
}

/** Chebyshev-only zone, no parts axis:
 *  `position/{zone}/{zoom}/{chunk_idx}.bin.gz`. */
export interface ChebyshevZoom {
	shape: 'chunked';
	chunks: number;
	chunk_years: number;
	start_jd: number;
	end_jd: number;
}

/** Probe zones — `chunked` shape but emitted directly at zone level (no
 *  `zooms` wrapper) so the URL is `position/{zone}/{chunk}.bin.gz`. */
export interface ProbeZoneMetadata {
	shape: 'chunked';
	chunks: number;
	chunk_years: number;
	start_jd: number;
	end_jd: number;
	subchunk_days: number;
	float64_coeffs: boolean;
	/** NAIF ID of the body each probe's position is relative to (10=Sun for
	 *  interplanetary, 199=Mercury for probes/mercury, …). The frontend looks
	 *  up the body's world position and GM via this id. */
	fit_center_naif_id: number;
	parent_id_type?: string;
}

/** Per-zoom metadata. Tagged union dispatched on the `shape` field. */
export type ZoomMetadata = PartedZoom | DateSegmentedZoom | ChunkIndexedZoom | ChebyshevZoom;

export function isParted(zoom: ZoomMetadata): zoom is PartedZoom {
	return zoom.shape === 'parted';
}

export function isDateSegmented(zoom: ZoomMetadata): zoom is DateSegmentedZoom {
	return zoom.shape === 'chunked-parted' && zoom.label === 'date';
}

export function isChunkIndexed(zoom: ZoomMetadata): zoom is ChunkIndexedZoom {
	return zoom.shape === 'chunked-parted' && zoom.label === 'index';
}

export function isChebyshev(zoom: ZoomMetadata): zoom is ChebyshevZoom {
	return zoom.shape === 'chunked';
}

const DAYS_PER_YEAR = 365.25;

/**
 * Resolve a JD to a chunk index for a chunk-indexed zoom, clamped so boundary
 * JDs map onto the last chunk instead of overflowing.
 */
export function chunkIndexForJd(zoom: ChunkIndexedZoom, jd: number): number {
	const idx = Math.floor((jd - zoom.start_jd) / (zoom.chunk_years * DAYS_PER_YEAR));
	return Math.max(0, Math.min(zoom.chunks - 1, idx));
}

export interface ZoneMetadata {
	zooms: Record<string, ZoomMetadata>;
	/** ID-type prefix for col-2 (parent) numeric values across this zone's
	 *  files. The frontend rebuilds full parent ids as `${prefix}-${col2}`.
	 *  Defaults to `"naif"` when absent (legacy zones predate the field). */
	parent_id_type?: string;
}

/** Probe zone entries in `metadata.position.zones` are flat (no `zooms`
 *  wrapper) — they carry the chunked-shape fields directly. Detect with
 *  `'shape' in entry` since regular entries have a `zooms` key instead. */
export type ZoneOrProbeMetadata = ZoneMetadata | ProbeZoneMetadata;

export function isProbeZone(entry: ZoneOrProbeMetadata): entry is ProbeZoneMetadata {
	return (entry as ProbeZoneMetadata).shape === 'chunked';
}

/**
 * Clamp `date` into the segmented zoom's date range and return the ISO
 * `YYYY-MM-DD` snapshot string for the URL builder. Snapshots are exported
 * daily so the integer-day truncation lands on a real export.
 */
export function snapshotDate(zoom: DateSegmentedZoom, date: Date): string {
	const t = date.getTime();
	const startMs = Date.parse(`${zoom.start_date}T00:00:00Z`);
	const endMs = Date.parse(`${zoom.end_date}T00:00:00Z`);
	const clamped = Math.min(Math.max(t, startMs), endMs);
	return new Date(clamped).toISOString().slice(0, 10);
}

export interface PositionMetadata {
	zones: Record<string, ZoneOrProbeMetadata>;
}

export interface Metadata {
	position: PositionMetadata;
	object_bundles: ObjectBundles;
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
 * Walk `metadata.position.zones` and pick out the chebyshev zones (those whose
 * zoom-0 has `shape: "chunked"`), folding them into the per-zone params map
 * the `ChebyshevStore` consumes. Returns an empty map when no chebyshev zones
 * exist; callers gate construction on `size > 0`.
 */
export function chebyshevZoneParams(meta: Metadata): Map<string, ChebyshevZoneParams> {
	const out = new Map<string, ChebyshevZoneParams>();
	for (const [zone, zoneData] of Object.entries(meta.position.zones)) {
		if (isProbeZone(zoneData)) continue;
		const zoom0 = zoneData.zooms['0'];
		if (!zoom0 || zoom0.shape !== 'chunked') continue;
		out.set(zone, {
			chunks: zoom0.chunks,
			chunk_years: zoom0.chunk_years,
			start_jd: zoom0.start_jd,
			end_jd: zoom0.end_jd
		});
	}
	return out;
}

/**
 * Probe zones (`probes/*`) — flat manifest entries the `ProbeStore` consumes.
 * Returns an empty map when no probe zones exist; callers gate construction
 * on `size > 0`.
 */
export function probeZoneParams(meta: Metadata): Map<string, ProbeZoneParams> {
	const out = new Map<string, ProbeZoneParams>();
	for (const [zone, zoneData] of Object.entries(meta.position.zones)) {
		if (!isProbeZone(zoneData)) continue;
		out.set(zone, {
			chunks: zoneData.chunks,
			chunk_years: zoneData.chunk_years,
			start_jd: zoneData.start_jd,
			end_jd: zoneData.end_jd,
			float64_coeffs: zoneData.float64_coeffs,
			fit_center_naif_id: zoneData.fit_center_naif_id
		});
	}
	return out;
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
