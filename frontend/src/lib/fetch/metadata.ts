/**
 * Shared loader for `/data/v1/metadata.json`. Memoized — every consumer
 * (chunk prefetcher, Chebyshev store init, object-detail bundle lookup)
 * shares the same fetch.
 */

import type { ChebyshevZoneParams } from './position/chebyshev/store';
import type { ProbeZoneParams } from './position/probes/store';
import { DATA_BASE, setDataVersions } from './data-base';

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

/** Static parted zone: `position/{zone}/[{zoom}/]{part}.bin.gz` (the `{zoom}`
 *  segment only for multi-zoom zones — see {@link zoneLayers}). */
export interface PartedZoom {
	shape: 'parted';
	parts: number;
}

/** Time-chunked + parted, ISO-date label (currently `earth`):
 *  `position/{zone}/[{zoom}/]{YYYY-MM-DD}/{part}.bin.gz`. The available snapshot
 *  dates are sparse and irregular (recent CelesTrak dailies + historical
 *  Space-Track weeklies), so `parts_by_date` doubles as the date index — its
 *  keys are exactly the exported snapshots — and gives each date's part count
 *  (historical weeks carry the full decayed catalog, recent dailies fewer).
 *  `parts` is the max across dates, a convenience bound. */
export interface DateSegmentedZoom {
	shape: 'chunked-parted';
	label: 'date';
	start_date: string;
	end_date: string;
	parts: number;
	parts_by_date: Record<string, number>;
}

/** Time-chunked + parted, integer chunk-idx label (currently `moons`):
 *  `position/{zone}/[{zoom}/]{chunk_idx}/{part}.bin.gz`. */
export interface ChunkIndexedZoom {
	shape: 'chunked-parted';
	label: 'index';
	chunks: number;
	chunk_days: number;
	start_jd: number;
	parts: number;
}

/** Chebyshev-only zone, no parts axis:
 *  `position/{zone}/[{zoom}/]{chunk_idx}.bin.gz` (the `{zoom}` segment only for
 *  `major`, which shares its zone with the Horizons elements tiers). */
export interface ChebyshevZoom {
	shape: 'chunked';
	chunks: number;
	chunk_days: number;
	start_jd: number;
	end_jd: number;
}

/** Probe zones — emitted directly at zone level (no `zooms` wrapper) so the URL
 *  is `position/{zone}/{chunk}.bin.gz`. The distinct `probes` shape tag tells
 *  them apart from flat chebyshev zones, which also sit at zone level. */
export interface ProbeZoneMetadata {
	shape: 'probes';
	chunks: number;
	chunk_days: number;
	start_jd: number;
	end_jd: number;
	subchunk_days: number;
	float64_coeffs: boolean;
	/** NAIF ID of the body each probe's position is relative to (10=Sun for
	 *  interplanetary, 199=Mercury for probes/mercury, …). The frontend looks
	 *  up the body's world position and GM via this id. */
	fit_center_naif_id: number;
	parent_id_type?: string;
	/** Inclusive-inclusive `[start, end]` ranges of chunk indices that actually
	 *  have a `.bin.gz` on the export. Zones are sparse (Pluto = New Horizons
	 *  flyby only, …) and most slots in `[0, chunks)` have no file; clients
	 *  must treat any chunk index outside every range as authoritatively absent
	 *  and skip the GET. Ranges are sorted ascending and non-overlapping. */
	present: [number, number][];
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

/** Minimal shape needed to map a JD to a chunk index. */
export interface ChunkRange {
	chunks: number;
	chunk_days: number;
	start_jd: number;
}

/**
 * Resolve a JD to a chunk index, clamped so boundary JDs map onto the last
 * chunk instead of overflowing.
 */
export function chunkIndexForJd(zone: ChunkRange, jd: number): number {
	const idx = Math.floor((jd - zone.start_jd) / zone.chunk_days);
	return Math.max(0, Math.min(zone.chunks - 1, idx));
}

/** ID-type prefix for col-2 (parent) numeric values across a zone's files. The
 *  frontend rebuilds full parent ids as `${prefix}-${col2}`. Defaults to
 *  `"naif"` when absent (legacy zones predate the field). */
interface HasParentIdType {
	parent_id_type?: string;
}

/** Multi-zoom zone (`major`, `small_bodies/{class}`): shapes nested under a
 *  `zooms` map, URL keeps a `{zoom}` segment. */
export interface ZoneMetadata extends HasParentIdType {
	zooms: Record<string, ZoomMetadata>;
}

/** Structurally single-zoom zone: the shape sits at zone level, URL drops the
 *  `{zoom}` segment. */
export type FlatZoneMetadata = ZoomMetadata & HasParentIdType;

export type ZoneOrProbeMetadata = ZoneMetadata | FlatZoneMetadata | ProbeZoneMetadata;

export function isProbeZone(entry: ZoneOrProbeMetadata): entry is ProbeZoneMetadata {
	return 'shape' in entry && entry.shape === 'probes';
}

export function isZoomedZone(entry: ZoneOrProbeMetadata): entry is ZoneMetadata {
	return 'zooms' in entry;
}

/** A zone's loadable layers, normalized across flat and multi-zoom entries.
 *  `zoom` is null for flat zones (URL omits the segment). Probe zones yield
 *  nothing — they load through the ProbeStore. */
export interface ZoneLayer {
	zoom: number | null;
	data: ZoomMetadata;
}

export function zoneLayers(entry: ZoneOrProbeMetadata): ZoneLayer[] {
	if (isProbeZone(entry)) return [];
	if (isZoomedZone(entry))
		return Object.entries(entry.zooms).map(([z, data]) => ({ zoom: Number(z), data }));
	return [{ zoom: null, data: entry }];
}

/** The lone ZoomMetadata of a flat zone; undefined for multi-zoom or probe zones. */
export function flatZoom(entry: ZoneOrProbeMetadata): ZoomMetadata | undefined {
	return !isZoomedZone(entry) && !isProbeZone(entry) ? entry : undefined;
}

/** Sorted UTC-midnight ms of every available snapshot date, memoised per zoom
 *  (the metadata object is stable for the session). */
const sortedDateMsCache = new WeakMap<DateSegmentedZoom, number[]>();

function sortedDateMs(zoom: DateSegmentedZoom): number[] {
	let arr = sortedDateMsCache.get(zoom);
	if (!arr) {
		arr = Object.keys(zoom.parts_by_date)
			.map((d) => Date.parse(`${d}T00:00:00Z`))
			.sort((a, b) => a - b);
		sortedDateMsCache.set(zoom, arr);
	}
	return arr;
}

/**
 * Return the ISO `YYYY-MM-DD` of the exported snapshot nearest `date`. Snapshot
 * dates are sparse and irregular (weekly history + daily recent), so this snaps
 * to the closest available date rather than truncating — a plain day-truncation
 * would miss the export for any non-daily date. Out-of-range dates clamp to the
 * first/last snapshot.
 */
export function snapshotDate(zoom: DateSegmentedZoom, date: Date): string {
	const dates = sortedDateMs(zoom);
	const t = date.getTime();
	const toIso = (ms: number) => new Date(ms).toISOString().slice(0, 10);
	if (t <= dates[0]) return toIso(dates[0]);
	if (t >= dates[dates.length - 1]) return toIso(dates[dates.length - 1]);
	let lo = 0;
	let hi = dates.length - 1;
	while (lo < hi) {
		const mid = (lo + hi) >> 1;
		if (dates[mid] < t) lo = mid + 1;
		else hi = mid;
	}
	// dates[lo] is the first >= t; pick whichever neighbor is closer.
	const prev = dates[lo - 1];
	const next = dates[lo];
	return toIso(t - prev <= next - t ? prev : next);
}

/** Part count for a specific snapshot date, capped by `cap` (0 = uncapped).
 *  `isoDate` must be a key of `parts_by_date` (i.e. from {@link snapshotDate});
 *  falls back to the zone max otherwise. */
export function partsForDate(zoom: DateSegmentedZoom, isoDate: string, cap = 0): number {
	const parts = zoom.parts_by_date[isoDate] ?? zoom.parts;
	return cap > 0 ? Math.min(parts, cap) : parts;
}

/** A probe's SPK coverage envelope (start, end JD) across every zone it
 *  touches. Lives on the probe's `__global__` entry (`GlobalObjectData.coverage`);
 *  read only for the focused probe. Absent on legacy exports. */
export interface ProbeCoverage {
	start_jd: number;
	end_jd: number;
}

export interface PositionMetadata {
	zones: Record<string, ZoneOrProbeMetadata>;
}

/**
 * Cubemap-skybox bundle metadata embedded at the top level. The renderer
 * picks the largest tier whose per-face size fits the device's max texture
 * dimension and loads the six face WebPs into a `CubeTexture` that becomes
 * `scene.background`. Face URLs:
 * `/v1/textures/{skybox.id}/{tier}_{face}.webp`.
 */
export interface SkyboxMetadata {
	id: string;
	type: 'cubemap_skybox';
	encoding: 'webp';
	frame: string;
	faces: string[];
	tiers: string[];
	tier_face_size: Record<string, number>;
	source: string;
	organisation: string;
	attribution?: string;
	description?: string;
}

export interface Metadata {
	position: PositionMetadata;
	object_bundles: ObjectBundles;
	/** Bucket counts for `nomenclature/details/{__global__|<lang>}/{bucket}.json.gz`.
	 *  Keyed identically to `object_bundles`. Bucket id is computed from
	 *  `hash("${bodyId}:${featureId}") % N` so a body's features cluster into one
	 *  bundle — opening one feature warms the rest. Optional so frontends
	 *  loading a pre-feature-details export degrade gracefully. */
	feature_bundles?: ObjectBundles;
	/** Bucket counts for `groups/{__global__|<lang>}/{bucket}.json.gz`. Bucket
	 *  id is `hashBucket(slug, N)`. Optional so frontends loading a pre-groups
	 *  export degrade gracefully. */
	group_bundles?: ObjectBundles;
	/** Per-content-class cache-busting tokens (content hashes). The frontend
	 *  appends `versions[class]` as `?v=` on URLs for classes served under an
	 *  immutable `Cache-Control` rule. Optional so pre-versioning exports load
	 *  (those URLs degrade to the revalidating default). Mirrors
	 *  `VERSIONED_CLASSES` in `data/.../pipeline/orchestrator.py`. */
	versions?: Record<string, string>;
	skybox?: SkyboxMetadata;
}

let pending: Promise<Metadata> | null = null;

export function fetchMetadata(): Promise<Metadata> {
	if (pending) return pending;
	pending = fetch(`${DATA_BASE}/v1/metadata.json`)
		.then((r) => {
			if (!r.ok) throw new Error(`Failed to fetch metadata: ${r.status}`);
			return r.json() as Promise<Metadata>;
		})
		.then((meta) => {
			// Publish version tokens before the resolved metadata reaches any
			// consumer, so `versionedUrl` always sees them.
			setDataVersions(meta.versions);
			return meta;
		});
	return pending;
}

/**
 * The chebyshev zones from `metadata.position.zones`, as the per-zone params
 * `ChebyshevStore` consumes. Cheb lives at `zooms['0']` for `major`, at zone
 * level for flat zones (`major_asteroids`, `moons/*`); `zoom` records which (0
 * vs null) for the URL. Empty when none exist — callers gate on `size > 0`.
 */
export function chebyshevZoneParams(meta: Metadata): Map<string, ChebyshevZoneParams> {
	const out = new Map<string, ChebyshevZoneParams>();
	for (const [zone, zoneData] of Object.entries(meta.position.zones)) {
		if (isProbeZone(zoneData)) continue;
		const zoom = isZoomedZone(zoneData) ? 0 : null;
		const cheb = zoom === 0 ? (zoneData as ZoneMetadata).zooms['0'] : (zoneData as ZoomMetadata);
		if (!cheb || !isChebyshev(cheb)) continue;
		out.set(zone, {
			zoom,
			chunks: cheb.chunks,
			chunk_days: cheb.chunk_days,
			start_jd: cheb.start_jd,
			end_jd: cheb.end_jd
		});
	}
	return out;
}

/**
 * Probe zones (`probes/*`) — flat manifest entries the `ProbeStore` consumes.
 * Returns an empty map when no probe zones exist; callers gate construction
 * on `size > 0`.
 *
 * `interplanetary` is intentionally inserted last so the `ProbeStore`'s
 * first-match-wins resolution prefers a planet-centric zone over the catch-all
 * heliocentric one. A flyby probe is emitted into both zones at the same jd
 * (see `data/.../trace.py`), and elements derived against the Sun would render
 * as a meaningless near-hyperbolic curve while the probe is captured around a
 * planet (e=>1 because the probe's Sun-relative velocity is dominated by the
 * planet's orbital velocity).
 */
export function probeZoneParams(meta: Metadata): Map<string, ProbeZoneParams> {
	const out = new Map<string, ProbeZoneParams>();
	const entries = Object.entries(meta.position.zones)
		.filter(([, z]) => isProbeZone(z))
		.sort(([a], [b]) => {
			const aLast = a === 'probes/interplanetary' ? 1 : 0;
			const bLast = b === 'probes/interplanetary' ? 1 : 0;
			return aLast - bLast || a.localeCompare(b);
		});
	for (const [zone, zoneData] of entries) {
		if (!isProbeZone(zoneData)) continue;
		out.set(zone, {
			chunks: zoneData.chunks,
			chunk_days: zoneData.chunk_days,
			start_jd: zoneData.start_jd,
			end_jd: zoneData.end_jd,
			float64_coeffs: zoneData.float64_coeffs,
			fit_center_naif_id: zoneData.fit_center_naif_id,
			present: zoneData.present
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
