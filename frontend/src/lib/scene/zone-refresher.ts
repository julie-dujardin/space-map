/**
 * Hot-reload driver for zones whose data is sliced by sim time. Two slicings:
 *   - **time-segmented** (`earth` SGP4 sats): one chunk set per ISO `YYYY-MM-DD`
 *     snapshot; the desired snapshot is chosen by clamping the sim date into
 *     the zoom's date range.
 *   - **chunk-indexed** (`moons` Method-C secular elements): one chunk set per
 *     `chunk_years` window starting at `start_jd`; the desired index is
 *     `floor((jd - start_jd) / (chunk_years * 365.25))`.
 *
 * On each `tick(date)`, every registered zone checks whether the desired slice
 * has diverged from what's resident; if so, it loads the new slice and
 * reconciles into the ContextManager. Reconciliation differs by zone type:
 *   - time-segmented: bucket by parentId in `spacecraftByParent` (membership
 *     can change across snapshots — added/removed satellites).
 *   - chunk-indexed: mutate existing bodies in `bodiesById` in place by id
 *     (membership is stable across chunks; only the orbital elements change).
 *
 * Pre-loading strategies (the asymmetry exists because off-window propagation
 * behaves very differently):
 *   - Chunk-indexed: **full preload** — `loader.process()` is fired ahead for
 *     `[idx-1, idx+1]` and the resolved `PositionedBody[][]` is held in
 *     `state.preloads`. On a boundary crossing the swap awaits this already-
 *     resolved promise, so the new elements land in the same microtask and
 *     no frame propagates with stale Method-C elements. (Stale Method-C
 *     extrapolates ~chunk_years of secular drift in `om`/`w`, sending moons
 *     to nonsense positions — visible as "moons disappear".)
 *   - Time-segmented: **HTTP-cache prefetch** of `[prev-day, next-day]` only.
 *     Earth has 20 parts × ~25K rows per snapshot; full preload would cost
 *     ~hundreds of MB. SGP4 propagators degrade gracefully past TLE epoch
 *     so the visible artifact is "sats lag behind" for the fetch+decode
 *     window, not catastrophic disappearance — HTTP warm is enough to
 *     shorten that window without holding parsed copies in memory.
 *
 * Concurrency is per-zone (`inFlight`); zones don't block each other. Time-
 * segmented zones additionally rate-limit load *starts* to
 * `MIN_LOAD_INTERVAL_MS` to avoid hammering during fast clock drag. Chunk-
 * indexed zones rely on single-flight only — preload covers most cases, and
 * stale chunks must not be allowed to linger.
 */

import { ObjectType, type PositionedBody } from '$lib/types/objects';
import {
	chunkIndexForJd,
	isChunkIndexed,
	isTimeSegmented,
	snapshotDate,
	type ChunkIndexedZoom,
	type Metadata,
	type TimeSegmentedZoom
} from '$lib/fetch/metadata';
import { ChunkLoader } from '$lib/fetch/elements/chunk';
import { dateToJD } from '$lib/format/date';
import type { ContextManager } from '$lib/scene/context-manager.svelte';

const MIN_LOAD_INTERVAL_MS = 2000;

interface BaseZoneState {
	zone: string;
	zoom: number;
	parts: number;
	inFlight: Promise<void> | null;
}

interface TimeZoneState extends BaseZoneState {
	kind: 'time';
	zoomData: TimeSegmentedZoom;
	/** Snapshot date string of the currently loaded data. */
	currentTime: string;
	/** Bucket keys this zone wrote into on the last load — used to clean up
	 *  buckets that vanish in a newer snapshot. Empty until the first refresh. */
	knownBuckets: Set<string>;
	lastLoadStartMs: number;
}

interface ChunkZoneState extends BaseZoneState {
	kind: 'chunk';
	zoomData: ChunkIndexedZoom;
	/** Index of the chunk currently resident in `ctx.bodiesById`. */
	currentIdx: number;
	/** Pre-resolved bodies for neighbor chunks `[currentIdx-1, currentIdx+1]`,
	 *  keyed by chunk index. Each value is a promise that resolves to the
	 *  per-part `PositionedBody[]` arrays returned by `loader.process()`.
	 *  Populated at construction and after each successful swap; entries
	 *  outside the neighbor window are pruned to bound memory. A boundary
	 *  crossing awaits the matching entry instead of issuing a fresh
	 *  `process()` so the swap lands in the next microtask. */
	preloads: Map<number, Promise<PositionedBody[][]>>;
}

type ZoneState = TimeZoneState | ChunkZoneState;

export class ZoneRefresher {
	private readonly zones: ZoneState[] = [];

	constructor(
		private readonly ctx: ContextManager,
		metadata: Metadata,
		private readonly loader: ChunkLoader,
		initialDate: Date
	) {
		const initialJd = dateToJD(initialDate);
		for (const [zone, zoneData] of Object.entries(metadata.zones)) {
			for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms)) {
				const zoom = Number(zoomStr);
				const parts = Math.min(zoomData.parts, 20);
				if (isTimeSegmented(zoomData)) {
					const state: TimeZoneState = {
						kind: 'time',
						zone,
						zoom,
						parts,
						zoomData,
						currentTime: snapshotDate(zoomData, initialDate),
						knownBuckets: new Set(),
						inFlight: null,
						lastLoadStartMs: -Infinity
					};
					this.zones.push(state);
					this.prefetchTimeNeighbors(state, initialDate);
				} else if (isChunkIndexed(zoomData)) {
					const state: ChunkZoneState = {
						kind: 'chunk',
						zone,
						zoom,
						parts,
						zoomData,
						currentIdx: chunkIndexForJd(zoomData, initialJd),
						inFlight: null,
						preloads: new Map()
					};
					this.zones.push(state);
					this.preloadChunkNeighbors(state, initialDate);
				}
			}
		}
	}

	/** Call from the renderer's per-frame loop on jd change. Cheap when nothing
	 *  needs reloading: a couple of date ops and string/number compares. */
	tick(date: Date): void {
		const jd = dateToJD(date);
		for (const state of this.zones) {
			if (state.inFlight) continue;
			if (state.kind === 'time') {
				const target = snapshotDate(state.zoomData, date);
				if (target === state.currentTime) continue;
				const nowMs = performance.now();
				if (nowMs - state.lastLoadStartMs < MIN_LOAD_INTERVAL_MS) continue;
				state.lastLoadStartMs = nowMs;
				state.inFlight = this.loadTime(state, target, date).finally(() => {
					state.inFlight = null;
				});
			} else {
				const target = chunkIndexForJd(state.zoomData, jd);
				if (target === state.currentIdx) continue;
				state.inFlight = this.loadChunk(state, target, date).finally(() => {
					state.inFlight = null;
				});
			}
		}
	}

	private async loadTime(z: TimeZoneState, time: string, date: Date): Promise<void> {
		const fromTime = z.currentTime;
		try {
			const chunks = await Promise.all(
				Array.from({ length: z.parts }, (_, part) =>
					this.loader.process(z.zone, z.zoom, part, date, time)
				)
			);

			const newBuckets = new Map<string, PositionedBody[]>();
			for (const chunk of chunks) {
				this.ctx.recordOrbitSources(chunk);
				for (const body of chunk) {
					const t = body.data.objectType;
					if (t !== ObjectType.SPACECRAFT && t !== ObjectType.DEBRIS) {
						// TODO: extend to asteroid zones once they become time-segmented.
						console.warn(
							`zone-refresher: unexpected non-spacecraft body in ${z.zone}: ${body.data.id} (type=${t})`
						);
						continue;
					}
					const key = body.data.parentId;
					const list = newBuckets.get(key) ?? [];
					list.push(body);
					newBuckets.set(key, list);
				}
			}

			let added = 0;
			let updated = 0;
			let removed = 0;

			for (const [key, freshBodies] of newBuckets) {
				const existing = this.ctx.spacecraftByParent.get(key) ?? [];
				const existingById = new Map(existing.map((b) => [b.data.id, b]));
				const merged: PositionedBody[] = [];
				for (const b of freshBodies) {
					const e = existingById.get(b.data.id);
					if (e) {
						e.data = b.data;
						e.position = b.position;
						// Don't overwrite optional fields with undefined: chunk.ts leaves
						// orbitElements/orbitCenter unset for non-major bodies, but the
						// placeholder for a focused sat needs its `orbitCenter` array to
						// stay alive — the per-frame loop mutates it to track parent
						// motion and syncs the orbit line via that reference.
						if (b.orbitElements !== undefined) e.orbitElements = b.orbitElements;
						if (b.orbitCenter !== undefined) e.orbitCenter = b.orbitCenter;
						if (b.trailBuffer !== undefined) e.trailBuffer = b.trailBuffer;
						merged.push(e);
						existingById.delete(b.data.id);
						updated++;
					} else {
						merged.push(b);
						added++;
					}
				}
				removed += existingById.size;
				this.ctx.spacecraftByParent.set(key, merged);
				this.ctx.dirtySpacecraftGroups.add(key);
			}

			// Buckets that existed last time but got nothing now: drop them so the
			// renderer can unwire the corresponding worker group.
			for (const key of z.knownBuckets) {
				if (newBuckets.has(key)) continue;
				const prev = this.ctx.spacecraftByParent.get(key);
				if (prev) {
					removed += prev.length;
					this.ctx.spacecraftByParent.delete(key);
					this.ctx.dirtySpacecraftGroups.add(key);
				}
			}

			z.knownBuckets = new Set(newBuckets.keys());
			z.currentTime = time;
			this.ctx.minorBodyVersion++;
			console.log(
				`zone-refresher: ${z.zone}@${fromTime} → ${time} (+${added} ~${updated} -${removed})`
			);
			this.prefetchTimeNeighbors(z, date);
		} catch (e) {
			console.warn(`zone-refresher: failed to refresh ${z.zone}@${time}:`, e);
		}
	}

	private async loadChunk(z: ChunkZoneState, target: number, date: Date): Promise<void> {
		const previous = z.currentIdx;
		// Optimistic update so a re-entrant tick during the fetch sees this
		// target as already-being-loaded and doesn't double-fire.
		z.currentIdx = target;
		try {
			// Fast path: neighbor preload covers most boundary crossings; the
			// promise is typically already resolved so the swap lands in the
			// next microtask, before the renderer can propagate stale elements.
			// Cold path (preload missed — e.g. user scrubbed past the neighbor
			// window in a single frame) issues a fresh process() call.
			let chunks = await z.preloads.get(target);
			if (!chunks) {
				chunks = await Promise.all(
					Array.from({ length: z.parts }, (_, part) =>
						this.loader.process(z.zone, z.zoom, part, date, String(target))
					)
				);
			}

			let updated = 0;
			let added = 0;
			for (const chunk of chunks) {
				this.ctx.recordOrbitSources(chunk);
				for (const fresh of chunk) {
					const existing = this.ctx.bodiesById.get(fresh.data.id);
					if (!existing) {
						// New body in this chunk — register it. Rare in practice (moons
						// membership is stable across Method-C chunks) but cheap.
						this.ctx.addBodies([fresh]);
						this.ctx.majorBodies.push(fresh);
						added++;
						continue;
					}
					existing.data = fresh.data;
					existing.position = fresh.position;
					if (fresh.orbitElements !== undefined) existing.orbitElements = fresh.orbitElements;
					if (fresh.orbitCenter !== undefined) existing.orbitCenter = fresh.orbitCenter;
					updated++;
				}
			}
			this.ctx.minorBodyVersion++;
			console.log(
				`zone-refresher: ${z.zone} chunk ${previous} → ${target} (+${added} ~${updated})`
			);
			this.preloadChunkNeighbors(z, date);
		} catch (e) {
			console.warn(`zone-refresher: ${z.zone} chunk reload failed (${previous} → ${target}):`, e);
			z.currentIdx = previous;
		}
	}

	/** Pre-process bodies for chunk-indexed neighbors `[currentIdx-1, currentIdx+1]`
	 *  (clamped). Each entry is a single in-flight `Promise.all(loader.process(...))`
	 *  per part; idempotent on existing entries (the LRU caches in
	 *  `fetchElements`/`fetchLabels` deduplicate repeat calls anyway, but
	 *  storing the promise here avoids re-running the bodies-build loop).
	 *  Out-of-window entries are pruned so the map stays bounded to ≤3
	 *  resolved chunks of bodies. */
	private preloadChunkNeighbors(z: ChunkZoneState, date: Date): void {
		const lo = Math.max(0, z.currentIdx - 1);
		const hi = Math.min(z.zoomData.chunks - 1, z.currentIdx + 1);
		for (let i = lo; i <= hi; i++) {
			if (z.preloads.has(i)) continue;
			const time = String(i);
			const promise = Promise.all(
				Array.from({ length: z.parts }, (_, part) =>
					this.loader.process(z.zone, z.zoom, part, date, time)
				)
			);
			// Drop a failed preload from the map so a later cold-path fetch
			// can retry instead of awaiting a permanently-rejected promise.
			promise.catch((e) => {
				console.warn(`zone-refresher: ${z.zone} chunk ${i} preload failed:`, e);
				z.preloads.delete(i);
			});
			z.preloads.set(i, promise);
		}
		for (const idx of z.preloads.keys()) {
			if (idx < lo || idx > hi) z.preloads.delete(idx);
		}
	}

	/** Warm the HTTP cache for the day-before and day-after snapshots on a
	 *  time-segmented zone so a snapshot rollover in either direction hits a
	 *  cached binary. Full preload (à la chunk-indexed) would cost ~hundreds
	 *  of MB for Earth's 20-part / ~25K-row snapshots; SGP4 propagators
	 *  degrade gracefully past TLE epoch, so HTTP warmth is enough to keep
	 *  the lag-behind window short without resident copies. */
	private prefetchTimeNeighbors(z: TimeZoneState, date: Date): void {
		const dayMs = 86400000;
		const before = snapshotDate(z.zoomData, new Date(date.getTime() - dayMs));
		const after = snapshotDate(z.zoomData, new Date(date.getTime() + dayMs));
		for (const time of new Set([before, after])) {
			if (time === z.currentTime) continue;
			for (let part = 0; part < z.parts; part++) {
				ChunkLoader.prefetch(z.zone, z.zoom, part, time);
			}
		}
	}
}
