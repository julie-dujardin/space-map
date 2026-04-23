/**
 * Per-zone cache of Chebyshev chunks.
 *
 * The export ships per-zone, per-time-chunk binaries under
 * `/data/v1/chebyshev/{zone}/{chunkIdx}/data.bin.gz`. A zone's manifest entry
 * gives `start_jd` and `chunk_years`, so the chunk index for any JD is just
 * `floor((jd - start_jd) / (chunk_years * 365.25))`.
 *
 * For now we eager-load the chunk containing the current JD plus its two
 * neighbors across every zone. Time scrubbing advances one chunk at a time, so
 * ±1 is enough to avoid a fetch stall at chunk boundaries; the tail chunk is
 * evicted when we slide forward.
 *
 * Bodies are keyed by their full object id (`<source>-<numeric>`), matching
 * the sidecar `data.id.gz` and the frontend `BodyData.id` convention.
 */

import { fetchChebyshev, type FetchedChebyshev } from '$lib/fetch/chebyshev/fetch';
import { chebyshevPositionKm, chebyshevPositionScene } from '$lib/fetch/chebyshev/propagate';
import { kmToScene } from '$lib/math/units';
import type { ChebyshevBody } from '$lib/fetch/chebyshev/parse';

export interface ChebyshevZoneManifest {
	chunks: number;
	start_jd: number;
	end_jd: number;
	chunk_years: number;
	body_count: number;
	total_bytes: number;
}

export interface ChebyshevManifest {
	version: number;
	zones: Record<string, ChebyshevZoneManifest>;
}

const DAYS_PER_YEAR = 365.25;
const NEIGHBOR_WINDOW = 1;

/**
 * Resolve a JD to a chunk index inside one zone, clamped to the valid range so
 * boundary JDs map onto the last chunk instead of returning -1.
 */
export function chunkIndexForJd(zone: ChebyshevZoneManifest, jd: number): number {
	const dt = jd - zone.start_jd;
	const idx = Math.floor(dt / (zone.chunk_years * DAYS_PER_YEAR));
	return Math.max(0, Math.min(zone.chunks - 1, idx));
}

interface BodyLocation {
	zone: string;
	chunkIdx: number;
	body: ChebyshevBody;
}

export class ChebyshevStore {
	private readonly manifest: ChebyshevManifest;
	/** `zone → chunkIdx → parsed chunk`. */
	private readonly chunks = new Map<string, Map<number, FetchedChebyshev>>();
	/** `objectId → zone` so getPosition can route without scanning zones. */
	private readonly idToZone = new Map<string, string>();

	constructor(manifest: ChebyshevManifest) {
		this.manifest = manifest;
	}

	zones(): string[] {
		return Object.keys(this.manifest.zones);
	}

	/**
	 * Load the chunks covering `jd` (and ±NEIGHBOR_WINDOW neighbors) for every
	 * zone in the manifest. Safe to call multiple times; already-loaded chunks
	 * are skipped.
	 */
	async ensure(jd: number): Promise<void> {
		const jobs: Promise<void>[] = [];
		for (const [zone, meta] of Object.entries(this.manifest.zones)) {
			const center = chunkIndexForJd(meta, jd);
			for (let d = -NEIGHBOR_WINDOW; d <= NEIGHBOR_WINDOW; d++) {
				const idx = center + d;
				if (idx < 0 || idx >= meta.chunks) continue;
				jobs.push(this.loadChunk(zone, idx));
			}
		}
		await Promise.all(jobs);
	}

	private async loadChunk(zone: string, chunkIdx: number): Promise<void> {
		let zoneMap = this.chunks.get(zone);
		if (zoneMap?.has(chunkIdx)) return;
		if (!zoneMap) {
			zoneMap = new Map();
			this.chunks.set(zone, zoneMap);
		}
		const chunk = await fetchChebyshev(zone, chunkIdx);
		zoneMap.set(chunkIdx, chunk);
		for (const id of chunk.ids) {
			// Multiple chunks list the same body; zone assignment is stable across
			// chunks by construction (same writer partitions). First write wins.
			if (!this.idToZone.has(id)) this.idToZone.set(id, zone);
		}
	}

	has(objectId: string): boolean {
		return this.idToZone.has(objectId);
	}

	private resolve(objectId: string, jd: number): BodyLocation | null {
		const zone = this.idToZone.get(objectId);
		if (zone === undefined) return null;
		const zoneMeta = this.manifest.zones[zone];
		const chunkIdx = chunkIndexForJd(zoneMeta, jd);
		const zoneMap = this.chunks.get(zone);
		const chunk = zoneMap?.get(chunkIdx);
		if (!chunk) return null;
		const rowIdx = chunk.ids.indexOf(objectId);
		if (rowIdx < 0) return null;
		return { zone, chunkIdx, body: chunk.bodies[rowIdx] };
	}

	/**
	 * Parent-relative position in Three.js scene units at `jd`. Returns null if
	 * the body isn't chebyshev-backed, its chunk isn't loaded, or `jd` is
	 * outside segment coverage.
	 */
	positionScene(objectId: string, jd: number): [number, number, number] | null {
		const loc = this.resolve(objectId, jd);
		if (!loc) return null;
		return chebyshevPositionScene(loc.body, jd);
	}

	/**
	 * Sample `pointCount` points in Three.js scene units spanning `periodDays`
	 * centered on `jd`, evenly spaced. The returned points are parent-relative
	 * (same frame the scene uses for orbit-line geometry).
	 *
	 * Returns null if the body isn't loaded. Samples outside the body's segment
	 * coverage become NaN triples (buildOrbitTrailPoints already filters on
	 * isFinite, so these drop out of the final curve).
	 */
	sampleOrbitScene(
		objectId: string,
		jd: number,
		periodDays: number,
		pointCount: number
	): [number, number, number][] | null {
		const loc = this.resolve(objectId, jd);
		if (!loc) return null;
		const pts: [number, number, number][] = new Array(pointCount);
		const half = periodDays / 2;
		for (let k = 0; k < pointCount; k++) {
			const t = jd - half + (k / (pointCount - 1)) * periodDays;
			const p = chebyshevPositionKm(loc.body, t);
			if (!p) {
				pts[k] = [NaN, NaN, NaN];
				continue;
			}
			// ECLIPJ2000 (x, y, z) → Three.js (x, z, -y), scaled into scene units.
			pts[k] = [kmToScene(p[0]), kmToScene(p[2]), -kmToScene(p[1])];
		}
		return pts;
	}
}

/**
 * Fetch `/data/v1/metadata.json` and, if it carries a `chebyshev` block,
 * eager-load the chunks around `jd`.
 */
export async function loadChebyshevStore(
	metadataUrl: string,
	jd: number
): Promise<ChebyshevStore | null> {
	const res = await fetch(metadataUrl);
	if (!res.ok) return null;
	const metadata = (await res.json()) as {
		chebyshev?: ChebyshevManifest;
	};
	if (!metadata.chebyshev) return null;
	const store = new ChebyshevStore(metadata.chebyshev);
	await store.ensure(jd);
	return store;
}
