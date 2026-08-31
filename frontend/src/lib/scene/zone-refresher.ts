/**
 * Hot-reload driver for time-sliced zones. Time-segmented (`earth` SGP4 sats,
 * one chunk set per ISO date) reconciles by parentId bucket in
 * `spacecraftByParent` and only HTTP-prefetches neighbor days (SGP4 degrades
 * gracefully past TLE epoch, so a full preload isn't worth hundreds of MB).
 * Chunk-indexed (`moons` Method-C, one set per `chunk_days` window) mutates
 * `bodiesById` in place and fully preloads `[idx-1, idx+1]`, since stale
 * secular drift sends moons to nonsense after one chunk.
 *
 * Concurrency: per-zone single-flight; time-segmented also rate-limits load
 * starts to `MIN_LOAD_INTERVAL_MS` against fast clock drag.
 */

import { ObjectType, type PositionedBody } from '$lib/types/objects';
import {
	chunkIndexForJd,
	dateCoverage,
	isChunkIndexed,
	isDateSegmented,
	partsForDate,
	snapshotDate,
	zoneLayers,
	type ChunkIndexedZoom,
	type DateCoverage,
	type DateSegmentedZoom,
	type Metadata
} from '$lib/fetch/metadata';
import { ChunkLoader } from '$lib/fetch/position/chunk';
import { dateToJD, jdToDate } from '$lib/format/date';
import { fetchLabels } from '$lib/fetch/position/labels';
import { passengerFor } from '$lib/fetch/position/probes/passenger';
import { ensureTargetStreamed } from '$lib/scene/setup/placeholder';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { getSettings } from '$lib/state/settings.svelte';

const MIN_LOAD_INTERVAL_MS = 2000;

interface BaseZoneState {
	zone: string;
	zoom: number | null;
	parts: number;
	parentIdType: string;
	inFlight: Promise<void> | null;
}

interface TimeZoneState extends BaseZoneState {
	kind: 'time';
	zoomData: DateSegmentedZoom;
	/** Snapshot date string of the currently loaded data. */
	currentTime: string;
	lastLoadStartMs: number;
	/** Per-zone part cap (0 = uncapped); part count is resolved per snapshot
	 *  date via {@link partsForDate} since date-segmented zones vary. */
	cap: number;
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

/** Consecutive reload failures before treating data as stale — a redeploy rotates
 *  the `?v=` tokens, so every reload then 404s/mismatches. */
const STALE_FAILURE_STREAK = 3;

export class ZoneRefresher {
	private readonly zones: ZoneState[] = [];
	/** Latest date seen by tick; lets {@link invalidateZone} re-fire without
	 *  waiting for the renderer (which gates refreshTick on jd advancing). */
	private latestDate: Date;
	/** Consecutive reload failures across zones; reset on any success. */
	private failureStreak = 0;
	/** Guards the one-shot `onDataStale` notification. */
	private staleNotified = false;

	constructor(
		private readonly ctx: ContextManager,
		metadata: Metadata,
		private readonly loader: ChunkLoader,
		initialDate: Date
	) {
		this.latestDate = initialDate;
		const initialJd = dateToJD(initialDate);
		const cap = getSettings().maxPartsPerZone;
		for (const [zone, zoneData] of Object.entries(metadata.position.zones)) {
			// zoneLayers yields nothing for probe zones — they load via ProbeStore.
			const parentIdType = zoneData.parent_id_type ?? 'naif';
			for (const { zoom, data: zoomData } of zoneLayers(zoneData)) {
				// Chebyshev zones (`shape: chunked`) are driven by the
				// ChebyshevStore, not this refresher; static-parted zones don't
				// fan out over time, so they don't need a refresher entry either.
				if (zoomData.shape === 'chunked' || zoomData.shape === 'parted') continue;
				const parts = cap > 0 ? Math.min(zoomData.parts, cap) : zoomData.parts;
				if (isDateSegmented(zoomData)) {
					const state: TimeZoneState = {
						kind: 'time',
						zone,
						zoom,
						parts,
						parentIdType,
						zoomData,
						currentTime: snapshotDate(zoomData, initialDate),
						inFlight: null,
						lastLoadStartMs: -Infinity,
						cap
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

	private recordSuccess(): void {
		this.failureStreak = 0;
	}

	/** Fire the one-shot stale signal after {@link STALE_FAILURE_STREAK} failures
	 *  in a row (usually a redeploy). */
	private recordFailure(): void {
		this.failureStreak++;
		if (this.failureStreak >= STALE_FAILURE_STREAK && !this.staleNotified) {
			this.staleNotified = true;
			this.ctx.onDataStale?.();
		}
	}

	/** Clear loaded state and re-fire {@link tick} now so paused-clock callers
	 *  (group-filter toggle) don't have to wait for a jd advance. */
	invalidateZone(zoneName: string): void {
		for (const z of this.zones) {
			if (z.zone !== zoneName || z.kind !== 'time') continue;
			z.currentTime = '';
			z.lastLoadStartMs = -Infinity;
		}
		this.tick(this.latestDate);
	}

	/** Earth-sat coverage at `jd` for the toast — from available snapshots, not the
	 *  resident chunk, so scrubbing to a covered time never falsely warns mid-load. */
	satelliteCoverage(jd: number): DateCoverage {
		const z = this.zones.find((s): s is TimeZoneState => s.kind === 'time' && s.zone === 'earth');
		if (!z) return { kind: 'covered' };
		return dateCoverage(z.zoomData, jdToDate(jd));
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
		this.latestDate = date;
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
				// one frame. Uncommon (chunks span chunk_days of sim time) but
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

	/** Stream a single target into the running scene if it isn't loaded — owns
	 *  the loader, so it's the entry point for in-session on-demand focus. */
	async ensureBody(targetId: string, date: Date): Promise<void> {
		if (this.ctx.getBody(targetId)) return;
		// Probes carry no orbital elements (the placeholder path can't build them)
		// and an out-of-coverage probe isn't in bodiesById at boot. Load its chunk
		// for the (coverage-snapped) date and re-run processProbes for it.
		if (targetId.startsWith('probe-')) {
			const store = this.ctx.probeStore;
			if (!store) return;
			const jd = dateToJD(date);
			// Started before the chunk wait so the two fetches overlap.
			const passengerPromise = passengerFor(targetId);
			await store.ensure(jd).done;
			// Registered before the store is asked anything about the craft: a
			// passenger answers off its carrier, the stamped fit center below
			// included.
			const passenger = await passengerPromise;
			if (passenger) store.registerCarried(passenger);
			// A record stamped to a small body (Deep Impact → Tempel 1) is gated
			// until that body can anchor it. Stream the body in and seed its
			// position so the probe below comes out placed even when no other
			// zone covers this date.
			const fcId = store.stampedFitCenterAt(targetId, jd);
			if (fcId) {
				if (!this.ctx.getBody(fcId)) {
					await ensureTargetStreamed(this.ctx, fcId, date, this.loader);
				}
				const fcBody = this.ctx.getBody(fcId);
				if (fcBody && !fcBody.positionUnknown && !this.loader.positions.has(fcId)) {
					this.loader.positions.set(fcId, fcBody.position);
				}
			}
			const labels = await fetchLabels();
			const target = this.loader
				.processProbes(store, date, labels)
				.find((b) => b.data.id === targetId);
			if (!target) {
				// No chunk anywhere for this craft: fall through to the global
				// bundle, which stands it in as an unplaceable focus target.
				await ensureTargetStreamed(this.ctx, targetId, date, this.loader);
				return;
			}
			this.ctx.bodies.addBodies([target]);
			this.ctx.credits.recordOrbitSources([target]);
			this.ctx.bodies.notifyBodiesAdded([targetId]);
			return;
		}
		await ensureTargetStreamed(this.ctx, targetId, date, this.loader);
	}

	private async loadTime(z: TimeZoneState, time: string, date: Date): Promise<void> {
		const fromTime = z.currentTime;
		try {
			const parts = partsForDate(z.zoomData, time, z.cap);
			const chunks = await Promise.all(
				Array.from({ length: parts }, (_, part) =>
					this.loader.process(z.zone, z.zoom, part, date, time, z.parentIdType)
				)
			);

			const isEarth = z.zone === 'earth';
			const earthFilter = isEarth ? this.ctx.earthSatFilter : null;
			const typeFilter = isEarth ? this.ctx.earthTypeFilter : null;
			let filteredOut = 0;
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
					if (earthFilter && !earthFilter.has(body.data.id)) {
						filteredOut++;
						continue;
					}
					if (typeFilter && !typeFilter.has(t)) {
						filteredOut++;
						continue;
					}
					const key = body.data.parentId;
					let bucket = newBuckets.get(key);
					if (!bucket) newBuckets.set(key, (bucket = new Map()));
					bucket.set(body.data.id, body);
				}
			}
			if (filteredOut > 0) {
				console.log(
					`zone-refresher: ${z.zone}@${time}: filtered out ${filteredOut} non-member bodies`
				);
			}

			let added = 0;
			let updated = 0;
			let removed = 0;
			const addedIds: string[] = [];

			// Reconcile to this snapshot's membership
			for (const [key, freshBodies] of newBuckets) {
				let bucket = this.ctx.bodies.spacecraftByParent.get(key);
				if (!bucket) {
					bucket = new Map();
					this.ctx.bodies.spacecraftByParent.set(key, bucket);
				}
				// Keep mesh-promoted ids: their PositionedBody is shared with the
				// mesh, so dropping the entry would orphan it on reappearance.
				for (const id of bucket.keys()) {
					if (freshBodies.has(id) || this.ctx.hasMeshBody?.(id)) continue;
					bucket.delete(id);
					removed++;
				}
				for (const [id, b] of freshBodies) {
					const e = bucket.get(id);
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
						updated++;
					} else {
						bucket.set(id, b);
						addedIds.push(id);
						added++;
					}
				}
				this.ctx.bodies.dirtySpacecraftGroups.add(key);
			}

			z.currentTime = time;
			this.ctx.bodies.minorBodyVersion++;
			this.ctx.bodies.notifyBodiesAdded(addedIds);
			// Re-evaluate emphasis even when this snapshot added no bodies (steady
			// membership, only the valid count moved) — notifyBodiesAdded won't.
			if (z.zone === 'earth') this.ctx.notifyEarthSatRollover();
			console.log(
				`zone-refresher: ${z.zone}@${fromTime} → ${time} (+${added} ~${updated} -${removed})`
			);
			this.prefetchTimeNeighbors(z, date);
			this.recordSuccess();
		} catch (e) {
			console.warn(`zone-refresher: failed to refresh ${z.zone}@${time}:`, e);
			this.recordFailure();
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
			this.recordSuccess();
		} catch (e) {
			console.warn(`zone-refresher: ${z.zone} chunk reload failed (${previous} → ${target}):`, e);
			z.currentIdx = previous;
			this.recordFailure();
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
			const parts = partsForDate(z.zoomData, time, z.cap);
			for (let part = 0; part < parts; part++) {
				ChunkLoader.prefetch(z.zone, z.zoom, part, time);
			}
		}
	}
}
