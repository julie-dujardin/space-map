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
import { chebyshevPositionScene } from '$lib/fetch/chebyshev/propagate';
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
	/** In-flight `loadChunk` promises keyed by `zone:chunkIdx`, so concurrent
	 * `ensure()` calls (e.g. per-frame) don't kick off duplicate fetches. */
	private readonly inflight = new Map<string, Promise<void>>();
	/** Last jd passed to `ensure()` — skips a full pass when nothing changed. */
	private lastEnsuredJd: number = NaN;

	constructor(manifest: ChebyshevManifest) {
		this.manifest = manifest;
	}

	zones(): string[] {
		return Object.keys(this.manifest.zones);
	}

	/**
	 * Load the chunks covering `jd` (and ±NEIGHBOR_WINDOW neighbors) for every
	 * zone in the manifest. Idempotent, safe to call every frame.
	 *
	 * Returns `true` if every zone's current-chunk is already loaded (so the
	 * caller can rely on position queries right away), `false` if a fetch was
	 * kicked off (position queries may return `null` until it resolves).
	 */
	ensure(jd: number): { ready: boolean; done: Promise<void> } {
		// Cheap skip: same jd as last call → caller already kicked ensures and
		// the async fetches (if any) are still resolving.
		if (jd === this.lastEnsuredJd) {
			return { ready: this.allCurrentChunksLoaded(jd), done: Promise.resolve() };
		}
		this.lastEnsuredJd = jd;
		const jobs: Promise<void>[] = [];
		let ready = true;
		for (const [zone, meta] of Object.entries(this.manifest.zones)) {
			const center = chunkIndexForJd(meta, jd);
			const zoneMap = this.chunks.get(zone);
			if (!zoneMap?.has(center)) ready = false;
			for (let d = -NEIGHBOR_WINDOW; d <= NEIGHBOR_WINDOW; d++) {
				const idx = center + d;
				if (idx < 0 || idx >= meta.chunks) continue;
				const job = this.loadChunk(zone, idx);
				if (job) jobs.push(job);
			}
		}
		return {
			ready,
			done: jobs.length > 0 ? Promise.all(jobs).then(() => undefined) : Promise.resolve()
		};
	}

	/** True when every zone's chunk for `jd` is resident in memory. */
	private allCurrentChunksLoaded(jd: number): boolean {
		for (const [zone, meta] of Object.entries(this.manifest.zones)) {
			const center = chunkIndexForJd(meta, jd);
			if (!this.chunks.get(zone)?.has(center)) return false;
		}
		return true;
	}

	private loadChunk(zone: string, chunkIdx: number): Promise<void> | null {
		const zoneMap = this.chunks.get(zone);
		if (zoneMap?.has(chunkIdx)) return null;
		const key = `${zone}:${chunkIdx}`;
		const existing = this.inflight.get(key);
		if (existing) return existing;
		const job = this.fetchAndStore(zone, chunkIdx);
		this.inflight.set(key, job);
		job.finally(() => this.inflight.delete(key));
		return job;
	}

	private async fetchAndStore(zone: string, chunkIdx: number): Promise<void> {
		let zoneMap = this.chunks.get(zone);
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

	/**
	 * Full JD extent of the zone hosting `objectId` — union of all its chunks.
	 * Distinguishes "jd permanently outside exported coverage" (toast-worthy)
	 * from "chunk still loading" (transient). Returns null if the body isn't
	 * tracked or its zone hasn't been seen yet.
	 */
	zoneCoverage(objectId: string): { start: number; end: number } | null {
		const zone = this.idToZone.get(objectId);
		if (zone === undefined) return null;
		const meta = this.manifest.zones[zone];
		if (!meta) return null;
		return { start: meta.start_jd, end: meta.end_jd };
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
	await store.ensure(jd).done;
	return store;
}
