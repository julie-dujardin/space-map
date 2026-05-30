/**
 * Hot-reload driver for time-sliced zones. Two slicings:
 *   - time-segmented (`earth` SGP4 sats): one chunk set per ISO date snapshot.
 *   - chunk-indexed (`moons` Method-C secular elements): one chunk set per
 *     `chunk_years` window from `start_jd`.
 *
 * Reconciliation: time-segmented buckets by parentId in `spacecraftByParent`
 * (membership flips across snapshots); chunk-indexed mutates `bodiesById` in
 * place (stable membership, only elements change).
 *
 * Pre-loading is asymmetric: chunk-indexed full-preloads parsed PositionedBody[][]
 * for `[idx-1, idx+1]` because stale Method-C secular drift sends moons to
 * nonsense after one chunk; time-segmented only HTTP-prefetches `[prev-day, next-day]`
 * (full preload would cost hundreds of MB) since SGP4 degrades gracefully past TLE epoch.
 *
 * Concurrency: per-zone single-flight. Time-segmented zones additionally
 * rate-limit load starts to `MIN_LOAD_INTERVAL_MS` against fast clock drag.
 */

import { ObjectType, type PositionedBody } from '$lib/types/objects';
import {
	chunkIndexForJd,
	isChunkIndexed,
	isDateSegmented,
	isProbeZone,
	snapshotDate,
	type ChunkIndexedZoom,
	type DateSegmentedZoom,
	type Metadata
} from '$lib/fetch/metadata';
import { ChunkLoader } from '$lib/fetch/position/chunk';
import { dateToJD } from '$lib/format/date';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

const MIN_LOAD_INTERVAL_MS = 2000;

interface BaseZoneState {
	zone: string;
	zoom: number;
	parts: number;
	parentIdType: string;
	inFlight: Promise<void> | null;
}

interface TimeZoneState extends BaseZoneState {
	kind: 'time';
	zoomData: DateSegmentedZoom;
	/** Snapshot date string of the currently loaded data. */
	currentTime: string;
	/** Bucket keys this zone wrote into on the last load — used to clean up
	 *  buckets that vanish in a newer snapshot. Empty until the first refresh. */
	knownBuckets: Set<string>;
	lastLoadStartMs: number;
}

/** A neighbor chunk preload — pending while `loader.process()` is in flight,
 *  ready once the per-part bodies are resolved. The 'ready' shape carries the
 *  bodies inline so `tick()` can apply the swap **synchronously** in the same
 *  frame as the boundary detection — without that, even an already-resolved
 *  promise costs a microtask gap that lets the renderer propagate one frame
 *  with stale Method-C elements (visible flicker on fast-precessing moons). */
type ChunkPreload =
	| { kind: 'pending'; promise: Promise<PositionedBody[][]> }
	| { kind: 'ready'; bodies: PositionedBody[][] };

interface ChunkZoneState extends BaseZoneState {
	kind: 'chunk';
	zoomData: ChunkIndexedZoom;
	/** Index of the chunk currently resident in `ctx.bodiesById`. */
	currentIdx: number;
	/** Neighbor preloads keyed by chunk index. Populated at construction and
	 *  after each successful swap; entries outside `[currentIdx-1, currentIdx+1]`
	 *  are pruned to bound memory (≤3 resolved chunks of bodies). */
	preloads: Map<number, ChunkPreload>;
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
		for (const [zone, zoneData] of Object.entries(metadata.position.zones)) {
			// Probe zones load through ProbeStore, not this refresher.
			if (isProbeZone(zoneData)) continue;
			for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms)) {
				const zoom = Number(zoomStr);
				// Chebyshev zones (`shape: chunked`) are driven by the
				// ChebyshevStore, not this refresher; static-parted zones don't
				// fan out over time, so they don't need a refresher entry either.
				if (zoomData.shape === 'chunked' || zoomData.shape === 'parted') continue;
				const parts = Math.min(zoomData.parts, 20);
				const parentIdType = zoneData.parent_id_type ?? 'naif';
				if (isDateSegmented(zoomData)) {
					const state: TimeZoneState = {
						kind: 'time',
						zone,
						zoom,
						parts,
						parentIdType,
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
						parentIdType,
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
	 *  needs reloading: a couple of date ops and string/number compares.
	 *
	 *  For chunk-indexed zones, a boundary crossing whose target preload is
	 *  already 'ready' applies the swap synchronously here — no async, no
	 *  microtask gap — so the same frame's `updatePositions` reads the new
	 *  Method-C elements and never propagates with a stale chunk's drift
	 *  rates. The async loadChunk path is reserved for the 'pending' and
	 *  cold-miss cases. */
	tick(date: Date): void {
		const jd = dateToJD(date);
		for (const state of this.zones) {
			if (state.kind === 'time') {
				if (state.inFlight) continue;
				const target = snapshotDate(state.zoomData, date);
				if (target === state.currentTime) continue;
				const nowMs = performance.now();
				if (nowMs - state.lastLoadStartMs < MIN_LOAD_INTERVAL_MS) continue;
				state.lastLoadStartMs = nowMs;
				state.inFlight = this.loadTime(state, target, date).finally(() => {
					state.inFlight = null;
				});
			} else {
				// Drain as many ready preloads as the user has scrubbed across in
				// one frame. Uncommon (chunks span chunk_years of sim time) but
				// keeps fast-scrub semantics tight.
				while (true) {
					const target = chunkIndexForJd(state.zoomData, jd);
					if (target === state.currentIdx) break;
					const preload = state.preloads.get(target);
					if (preload?.kind !== 'ready') break;
					const previous = state.currentIdx;
					state.currentIdx = target;
					this.applyChunkSwap(state, previous, target, preload.bodies);
					this.preloadChunkNeighbors(state, date);
				}
				if (state.inFlight) continue;
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
					this.loader.process(z.zone, z.zoom, part, date, time, z.parentIdType)
				)
			);

			const newBuckets = new Map<string, Map<string, PositionedBody>>();
			for (const chunk of chunks) {
				this.ctx.credits.recordOrbitSources(chunk);
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
					let bucket = newBuckets.get(key);
					if (!bucket) newBuckets.set(key, (bucket = new Map()));
					bucket.set(body.data.id, body);
				}
			}

			let added = 0;
			let updated = 0;
			let removed = 0;
			const addedIds: string[] = [];

			for (const [key, freshBodies] of newBuckets) {
				const existing = this.ctx.bodies.spacecraftByParent.get(key);
				const merged = new Map<string, PositionedBody>();
				const carriedIds = new Set<string>();
				for (const [id, b] of freshBodies) {
					const e = existing?.get(id);
					if (e) {
						e.data = b.data;
						e.position = b.position;
						// Don't overwrite optional fields with undefined: chunk.ts leaves
						// orbitElements/orbitCenter unset for non-major bodies, but the
						// placeholder for a focused sat needs its `orbitCenter` array to
						// stay alive — the per-frame loop mutates it to track parent
						// motion and syncs the trail via that reference.
						if (b.orbitElements !== undefined) e.orbitElements = b.orbitElements;
						if (b.orbitCenter !== undefined) e.orbitCenter = b.orbitCenter;
						merged.set(id, e);
						carriedIds.add(id);
						updated++;
					} else {
						merged.set(id, b);
						addedIds.push(id);
						added++;
					}
				}
				if (existing) {
					for (const id of existing.keys()) {
						if (!carriedIds.has(id)) removed++;
					}
				}
				this.ctx.bodies.spacecraftByParent.set(key, merged);
				this.ctx.bodies.dirtySpacecraftGroups.add(key);
			}

			// Buckets that existed last time but got nothing now: drop them so the
			// renderer can unwire the corresponding worker group.
			for (const key of z.knownBuckets) {
				if (newBuckets.has(key)) continue;
				const prev = this.ctx.bodies.spacecraftByParent.get(key);
				if (prev) {
					removed += prev.size;
					this.ctx.bodies.spacecraftByParent.delete(key);
					this.ctx.bodies.dirtySpacecraftGroups.add(key);
				}
			}

			z.knownBuckets = new Set(newBuckets.keys());
			z.currentTime = time;
			this.ctx.bodies.minorBodyVersion++;
			this.ctx.bodies.notifyBodiesAdded(addedIds);
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
			// 'pending' preload: await the in-flight promise. 'ready' isn't
			// reachable here — tick() applies those synchronously before
			// dispatching loadChunk. Cold miss (no entry, e.g. user scrubbed
			// past the neighbor window in one frame): fire a fresh process().
			const preload = z.preloads.get(target);
			let chunks: PositionedBody[][];
			if (preload?.kind === 'pending') {
				chunks = await preload.promise;
			} else {
				chunks = await Promise.all(
					Array.from({ length: z.parts }, (_, part) =>
						this.loader.process(z.zone, z.zoom, part, date, String(target), z.parentIdType)
					)
				);
			}
			this.applyChunkSwap(z, previous, target, chunks);
			this.preloadChunkNeighbors(z, date);
		} catch (e) {
			console.warn(`zone-refresher: ${z.zone} chunk reload failed (${previous} → ${target}):`, e);
			z.currentIdx = previous;
		}
	}

	/** Mutate `ctx.bodiesById` in place from a chunk's fresh bodies. Shared
	 *  by the synchronous swap (preload 'ready') and the async swap (preload
	 *  'pending' or cold miss). Caller is responsible for updating `currentIdx`
	 *  before invoking — `applyChunkSwap` only touches body fields and the
	 *  reactive minorBodyVersion. */
	private applyChunkSwap(
		z: ChunkZoneState,
		previous: number,
		target: number,
		chunks: PositionedBody[][]
	): void {
		let updated = 0;
		let added = 0;
		for (const chunk of chunks) {
			this.ctx.credits.recordOrbitSources(chunk);
			for (const fresh of chunk) {
				const existing = this.ctx.bodies.bodiesById.get(fresh.data.id);
				if (!existing) {
					// New body in this chunk — register it. Rare in practice (moons
					// membership is stable across Method-C chunks) but cheap.
					this.ctx.bodies.addBodies([fresh]);
					this.ctx.bodies.majorBodies.push(fresh);
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
		this.ctx.bodies.minorBodyVersion++;
		console.log(`zone-refresher: ${z.zone} chunk ${previous} → ${target} (+${added} ~${updated})`);
	}

	/** Pre-process bodies for chunk-indexed neighbors `[currentIdx-1, currentIdx+1]`
	 *  (clamped). Each entry starts as 'pending' (in-flight `loader.process()`
	 *  per part) and transitions to 'ready' on resolve so `tick()` can apply
	 *  the swap synchronously. The LRU caches in `fetchElements`/`fetchLabels`
	 *  dedupe the underlying fetches; storing the resolved bodies here avoids
	 *  re-running the bodies-build loop and — critically — lets the swap
	 *  happen without an `await` microtask. Out-of-window entries are pruned
	 *  so the map stays bounded to ≤3 resolved chunks. */
	private preloadChunkNeighbors(z: ChunkZoneState, date: Date): void {
		const lo = Math.max(0, z.currentIdx - 1);
		const hi = Math.min(z.zoomData.chunks - 1, z.currentIdx + 1);
		for (let i = lo; i <= hi; i++) {
			if (z.preloads.has(i)) continue;
			const time = String(i);
			const promise = Promise.all(
				Array.from({ length: z.parts }, (_, part) =>
					this.loader.process(z.zone, z.zoom, part, date, time, z.parentIdType)
				)
			);
			z.preloads.set(i, { kind: 'pending', promise });
			promise.then(
				(bodies) => {
					// Only transition to 'ready' if this entry is still the live
					// one — pruning during the fetch may have evicted it.
					if (z.preloads.get(i)?.kind === 'pending') {
						z.preloads.set(i, { kind: 'ready', bodies });
					}
				},
				(e) => {
					console.warn(`zone-refresher: ${z.zone} chunk ${i} preload failed:`, e);
					// Drop the failed entry so a later cold-path fetch can retry
					// instead of awaiting a permanently-rejected promise.
					if (z.preloads.get(i)?.kind === 'pending') z.preloads.delete(i);
				}
			);
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
