/**
 * Per-zone cache of Chebyshev chunks.
 *
 * The export ships per-zone, per-time-chunk binaries under
 * `/data/v1/position/{zone}/0/{chunkIdx}.bin.gz`. Each chebyshev zone in
 * `metadata.position.zones` (those with `shape: "chunked"`) declares its
 * own `chunks`, `chunk_years`, and `start_jd` — Saturn's 0.125-year cadence
 * and Pluto's 2-year cadence coexist with no global tier metadata. A zone's
 * chunk index for any JD is `floor((jd - start_jd) / (chunk_years * 365.25))`.
 *
 * For now we eager-load the chunk containing the current JD plus its two
 * neighbors across every zone. Time scrubbing advances one chunk at a time, so
 * ±1 is enough to avoid a fetch stall at chunk boundaries; the tail chunk is
 * evicted when we slide forward.
 *
 * Bodies are keyed by their full object id (`<prefix>-<numeric>`), built into
 * each body header and surfaced as `ChebyshevBody.id`.
 */

import { fetchChebyshev, type FetchedChebyshev } from '$lib/fetch/position/chebyshev/fetch';
import { chebyshevPositionScene } from '$lib/fetch/position/chebyshev/propagate';
import type { ChebyshevBody } from '$lib/fetch/position/chebyshev/parse';
import { chunkIndexForJd } from '$lib/fetch/metadata';

/** Walk the chunk for jd in every loaded zone and yield each body alongside
 *  the chunk's validity window (used by callers that build PositionedBody).
 *  Bodies whose chunk hasn't loaded yet are skipped — caller is responsible
 *  for awaiting `ensure(jd).done` first. */
export interface BodyWithWindow {
	zone: string;
	body: ChebyshevBody;
	startJd: number;
	endJd: number;
}

/** Per-zone chebyshev params, lifted from `metadata.position.zones[zone].zooms[0]`
 *  when the entry's `shape` is `"chunked"`. */
export interface ChebyshevZoneParams {
	chunks: number;
	chunk_years: number;
	start_jd: number;
	end_jd: number;
}

const NEIGHBOR_WINDOW = 1;

interface BodyLocation {
	zone: string;
	chunkIdx: number;
	body: ChebyshevBody;
}

export class ChebyshevStore {
	/** `zone → tier params`, populated at construction from the per-zone manifest. */
	private readonly zoneParams: Map<string, ChebyshevZoneParams>;
	/** `zone → chunkIdx → parsed chunk`. */
	private readonly chunks = new Map<string, Map<number, FetchedChebyshev>>();
	/** `objectId → zone` so getPosition can route without scanning zones. */
	private readonly idToZone = new Map<string, string>();
	/** In-flight `loadChunk` promises keyed by `zone:chunkIdx`, so concurrent
	 * `ensure()` calls (e.g. per-frame) don't kick off duplicate fetches. */
	private readonly inflight = new Map<string, Promise<void>>();
	/** Last jd passed to `ensure()` — skips a full pass when nothing changed. */
	private lastEnsuredJd: number = NaN;

	constructor(zoneParams: Map<string, ChebyshevZoneParams>) {
		this.zoneParams = zoneParams;
	}

	zones(): string[] {
		return Array.from(this.zoneParams.keys());
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
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			const zoneMap = this.chunks.get(zone);
			if (!zoneMap?.has(center)) ready = false;
			for (let d = -NEIGHBOR_WINDOW; d <= NEIGHBOR_WINDOW; d++) {
				const idx = center + d;
				if (idx < 0 || idx >= params.chunks) continue;
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
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
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
		const params = this.zoneParams.get(zone);
		if (!params) return null;
		return { start: params.start_jd, end: params.end_jd };
	}

	private resolve(objectId: string, jd: number): BodyLocation | null {
		const zone = this.idToZone.get(objectId);
		if (zone === undefined) return null;
		const params = this.zoneParams.get(zone);
		if (!params) return null;
		const chunkIdx = chunkIndexForJd(params, jd);
		const zoneMap = this.chunks.get(zone);
		const chunk = zoneMap?.get(chunkIdx);
		if (!chunk) return null;
		const rowIdx = chunk.ids.indexOf(objectId);
		if (rowIdx < 0) return null;
		return { zone, chunkIdx, body: chunk.bodies[rowIdx] };
	}

	/**
	 * Look up the parsed body record for `objectId` at `jd` — used by code
	 * paths that need the body header (`hasLocalized`, `radiusKm`, …) in
	 * addition to the position.
	 */
	body(objectId: string, jd: number): ChebyshevBody | null {
		return this.resolve(objectId, jd)?.body ?? null;
	}

	/**
	 * Iterate every chebyshev body covered by `jd` across every zone. Skips
	 * zones whose chunk for `jd` isn't loaded yet (callers must await
	 * `ensure(jd).done` to guarantee full coverage). Used by the scene loader
	 * to construct the major-body list — every Sun/planet/dwarf/perturber/
	 * whitelisted moon comes through here, since dropping the elements
	 * ride-along left chebyshev as the only source for these bodies.
	 */
	*bodiesAt(jd: number): IterableIterator<BodyWithWindow> {
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			for (const body of chunk.bodies) {
				yield { zone, body, startJd: chunk.startJd, endJd: chunk.endJd };
			}
		}
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
