/**
 * The chunk window behind `ChebyshevStore` and `ProbeStore`: per zone, the
 * chunk covering the clock plus one neighbour either side.
 *
 * Scrubbing advances one chunk at a time, so ±1 avoids a fetch stall at a
 * boundary, and anything further out is dropped — each chunk retains parsed
 * coefficient buffers.
 *
 * Subclasses supply the fetch and say which chunk indices exist; everything
 * about how a chunk is queried stays theirs.
 */

import { chunkIndexForJd, type ChunkRange } from '$lib/fetch/metadata';

const NEIGHBOR_WINDOW = 1;

/** Shared across every `ensure` with nothing in flight, of which there is one
 *  per frame. */
const RESOLVED: Promise<void> = Promise.resolve();

/** Cache key for one chunk of one zone. */
export function chunkKey(zone: string, chunkIdx: number): string {
	return `${zone}:${chunkIdx}`;
}

export abstract class ChunkWindow<TChunk, TParams extends ChunkRange> {
	/** `zone → chunkIdx → parsed chunk`. */
	protected readonly chunks = new Map<string, Map<number, TChunk>>();
	/** In-flight loads keyed by {@link chunkKey}, so concurrent `ensure()` calls
	 *  (per frame, among others) don't kick off duplicate fetches. */
	protected readonly inflight = new Map<string, Promise<void>>();
	/** Last jd passed to `ensure()` — skips a full pass when nothing changed. */
	private lastEnsuredJd: number = NaN;

	constructor(protected readonly zoneParams: Map<string, TParams>) {}

	zones(): string[] {
		return Array.from(this.zoneParams.keys());
	}

	/**
	 * Load the chunks covering `jd`, and warm their neighbours, for every zone.
	 * Idempotent, safe to call every frame.
	 *
	 * `ready` says whether every current chunk is resident now, so the caller
	 * can rely on position queries right away. `done` waits for the current
	 * chunks only: the neighbours are a warm-up and must not hold the first
	 * frame.
	 */
	ensure(jd: number): { ready: boolean; done: Promise<void> } {
		if (jd === this.lastEnsuredJd) {
			return { ready: this.allCurrentChunksLoaded(jd), done: this.pendingCurrent(jd) };
		}
		this.lastEnsuredJd = jd;
		const jobs: Promise<void>[] = [];
		const neighbors: [zone: string, params: TParams, idx: number][] = [];
		let ready = true;
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			if (this.isLoadable(params, center) && !this.isResident(zone, center)) {
				ready = false;
				const job = this.loadChunk(zone, params, center, 'high');
				if (job) jobs.push(job);
			}
			for (let d = -NEIGHBOR_WINDOW; d <= NEIGHBOR_WINDOW; d++) {
				const idx = center + d;
				if (d === 0 || idx < 0 || idx >= params.chunks) continue;
				if (this.isLoadable(params, idx)) neighbors.push([zone, params, idx]);
			}
			this.evictOutsideWindow(zone, center);
		}
		const done = jobs.length > 0 ? Promise.all(jobs).then(() => undefined) : RESOLVED;
		// Neighbours start once the current chunks are in: launched together they
		// share the link, and a boot on a slow one waits for the whole set.
		void done
			.catch(() => {})
			.then(() => {
				for (const [zone, params, idx] of neighbors) {
					this.loadChunk(zone, params, idx, 'low')?.catch(() => {});
				}
			});
		return { ready, done };
	}

	/**
	 * The current chunks still in flight. An `ensure` on an already-ensured jd
	 * must still hand back a wait: same jd doesn't mean loaded, and a second
	 * awaiter (a deep link grafting one body onto a running scene) must not
	 * proceed against absent chunks.
	 */
	private pendingCurrent(jd: number): Promise<void> {
		if (this.inflight.size === 0) return RESOLVED;
		let pending: Promise<void>[] | null = null;
		for (const [zone, params] of this.zoneParams) {
			const job = this.inflight.get(chunkKey(zone, chunkIndexForJd(params, jd)));
			if (job) (pending ??= []).push(job);
		}
		return pending ? Promise.all(pending).then(() => undefined) : RESOLVED;
	}

	/** True when every chunk for `jd` that exists is resident in memory. */
	protected allCurrentChunksLoaded(jd: number): boolean {
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			if (!this.isLoadable(params, center)) continue;
			if (!this.isResident(zone, center)) return false;
		}
		return true;
	}

	protected isResident(zone: string, chunkIdx: number): boolean {
		return this.chunks.get(zone)?.has(chunkIdx) ?? false;
	}

	private evictOutsideWindow(zone: string, center: number): void {
		const zoneMap = this.chunks.get(zone);
		if (!zoneMap) return;
		for (const idx of zoneMap.keys()) {
			if (idx < center - NEIGHBOR_WINDOW || idx > center + NEIGHBOR_WINDOW) zoneMap.delete(idx);
		}
	}

	/** Null when the chunk is already resident. */
	protected loadChunk(
		zone: string,
		params: TParams,
		chunkIdx: number,
		priority: RequestPriority
	): Promise<void> | null {
		if (this.isResident(zone, chunkIdx)) return null;
		const key = chunkKey(zone, chunkIdx);
		const existing = this.inflight.get(key);
		if (existing) return existing;
		const job = this.fetchAndStore(zone, params, chunkIdx, priority);
		this.inflight.set(key, job);
		job.finally(() => this.inflight.delete(key));
		return job;
	}

	private async fetchAndStore(
		zone: string,
		params: TParams,
		chunkIdx: number,
		priority: RequestPriority
	): Promise<void> {
		const chunk = await this.fetchChunk(zone, params, chunkIdx, priority);
		let zoneMap = this.chunks.get(zone);
		if (!zoneMap) this.chunks.set(zone, (zoneMap = new Map()));
		zoneMap.set(chunkIdx, chunk);
		this.afterStore(zone, chunk);
	}

	/** Whether a file exists for `chunkIdx`, consulted before any GET. */
	protected abstract isLoadable(params: TParams, chunkIdx: number): boolean;

	/** `priority` is high for a chunk the current frame needs, low for a
	 *  neighbour warmed behind it. */
	protected abstract fetchChunk(
		zone: string,
		params: TParams,
		chunkIdx: number,
		priority: RequestPriority
	): Promise<TChunk>;

	/** Update whatever the subclass indexes beside the chunk map. */
	protected abstract afterStore(zone: string, chunk: TChunk): void;
}
