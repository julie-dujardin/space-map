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
import { RetryBackoff } from '$lib/fetch/retry-backoff';

const NEIGHBOR_WINDOW = 1;

/** Shared across every pass with nothing in flight, of which there is one
 *  per frame. */
const RESOLVED: Promise<void> = Promise.resolve();

/** Cache key for one chunk of one zone. */
export function chunkKey(zone: string, chunkIdx: number): string {
	return `${zone}:${chunkIdx}`;
}

export abstract class ChunkWindow<TChunk, TParams extends ChunkRange> {
	/** `zone → chunkIdx → parsed chunk`. */
	protected readonly chunks = new Map<string, Map<number, TChunk>>();
	/** In-flight loads keyed by {@link chunkKey}, so concurrent passes (one per
	 *  frame, among others) don't kick off duplicate fetches. */
	protected readonly inflight = new Map<string, Promise<void>>();
	/** Chunks whose last load failed. {@link ensure} does not ask for one again
	 *  before its wait is over: it runs every frame. */
	private readonly retries = new RetryBackoff<string>(() => {
		this.retryDue = true;
		this._version++;
	});
	/** A wait ended since the last pass. */
	private retryDue = false;
	/** Last jd of a pass — {@link ensure} skips one when nothing changed. */
	private lastEnsuredJd: number = NaN;
	/** Bumped when a pass has something new to do: a chunk arrived, or a failed
	 *  one can be asked for again. The renderer watches it, so a clock that
	 *  stands still gets a position pass. */
	private _version = 0;

	constructor(protected readonly zoneParams: Map<string, TParams>) {}

	get version(): number {
		return this._version;
	}

	zones(): string[] {
		return Array.from(this.zoneParams.keys());
	}

	/**
	 * Keep the window on `jd`: load the chunks covering it, and warm their
	 * neighbours, for every zone. Idempotent, safe to call every frame.
	 */
	ensure(jd: number): void {
		if (jd === this.lastEnsuredJd && !this.retryDue) return;
		void this.pass(jd, false);
	}

	/**
	 * The chunks covering `jd`, for a caller that waits for them: position
	 * queries at `jd` are good when it resolves. It asks at once for a chunk
	 * that failed, whatever its wait, and rejects when one does not load.
	 *
	 * The wait is for the current chunks only: the neighbours are a warm-up and
	 * must not hold the first frame.
	 */
	load(jd: number): Promise<void> {
		return this.pass(jd, true);
	}

	/** Move the window to `jd`. `now` asks for a failed chunk inside its wait. */
	private pass(jd: number, now: boolean): Promise<void> {
		this.lastEnsuredJd = jd;
		this.retryDue = false;
		const jobs: Promise<void>[] = [];
		const neighbors: [zone: string, params: TParams, idx: number][] = [];
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			if (this.isLoadable(params, center)) {
				const job = this.loadChunk(zone, params, center, 'high', now);
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
		// share the link, and a boot on a slow one waits for the whole set. The
		// catch also answers for `ensure`, which does not read the outcome.
		void done
			.catch(() => {})
			.then(() => {
				for (const [zone, params, idx] of neighbors) {
					this.loadChunk(zone, params, idx, 'low')?.catch(() => {});
				}
			});
		return done;
	}

	/** Load the chunks covering `jd` and leave the window where it is: a scene
	 *  that waits for them still reads the date it shows. */
	request(jd: number): void {
		for (const [zone, params] of this.zoneParams) {
			const idx = chunkIndexForJd(params, jd);
			if (this.isLoadable(params, idx)) this.loadChunk(zone, params, idx, 'high')?.catch(() => {});
		}
	}

	/** True while a chunk that covers `jd` is on its way: of `zone`, or of any
	 *  zone. A chunk nobody asked for is not on its way. */
	loadingAt(jd: number, zone?: string): boolean {
		if (this.inflight.size === 0) return false;
		for (const [name, params] of this.zoneParams) {
			if (zone !== undefined && name !== zone) continue;
			if (this.inflight.has(chunkKey(name, chunkIndexForJd(params, jd)))) return true;
		}
		return false;
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

	/** The load of a chunk, in flight or started here. Null when there is none
	 *  to wait on: the chunk is resident, or it failed and waits for its retry
	 *  (`now` starts it all the same). */
	protected loadChunk(
		zone: string,
		params: TParams,
		chunkIdx: number,
		priority: RequestPriority,
		now = false
	): Promise<void> | null {
		if (this.isResident(zone, chunkIdx)) return null;
		const key = chunkKey(zone, chunkIdx);
		const existing = this.inflight.get(key);
		if (existing) return existing;
		if (!now && this.retries.waiting(key)) return null;
		return this.track(key, this.fetchAndStore(zone, params, chunkIdx, priority));
	}

	/** Hold `job` as the load in flight for `key`, and keep its outcome for
	 *  the retry wait. */
	protected track(key: string, job: Promise<void>): Promise<void> {
		this.inflight.set(key, job);
		const settle = (ok: boolean): void => {
			if (this.inflight.get(key) === job) this.inflight.delete(key);
			if (ok) this.retries.clear(key);
			else this.retries.fail(key);
		};
		job.then(
			() => settle(true),
			() => settle(false)
		);
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
		this._version++;
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
