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
 * has diverged from what's resident; if so, it fetches the new slice and
 * reconciles into the ContextManager. Reconciliation differs by zone type:
 *   - time-segmented: bucket by parentId in `spacecraftByParent` (membership
 *     can change across snapshots — added/removed satellites).
 *   - chunk-indexed: mutate existing bodies in `bodiesById` in place by id
 *     (membership is stable across chunks; only the orbital elements change).
 *
 * Throttling/concurrency is per-zone:
 *   - One load in flight at a time per zone (`inFlight`).
 *   - Time-segmented zones additionally rate-limit load *starts* to
 *     `MIN_LOAD_INTERVAL_MS` to avoid hammering during fast clock drag.
 *   - Chunk-indexed zones aren't rate-limited beyond single-flight: stale
 *     Method-C elements extrapolate wildly past their fit window, so any
 *     skipped boundary crossing produces visibly broken positions until the
 *     next load completes.
 *
 * Chunk-indexed zones also pre-warm the HTTP cache for `[idx-1, idx, idx+1]`
 * at construction and after each successful swap, so a boundary crossing in
 * either direction hits a cached binary. The fetch is still async (decompress
 * + parse + bodies build), so a small flicker can remain — fully eliminating
 * it would require either pre-loading the parsed bodies or gating the
 * propagator on validity.
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
					this.zones.push({
						kind: 'time',
						zone,
						zoom,
						parts,
						zoomData,
						currentTime: snapshotDate(zoomData, initialDate),
						knownBuckets: new Set(),
						inFlight: null,
						lastLoadStartMs: -Infinity
					});
				} else if (isChunkIndexed(zoomData)) {
					const state: ChunkZoneState = {
						kind: 'chunk',
						zone,
						zoom,
						parts,
						zoomData,
						currentIdx: chunkIndexForJd(zoomData, initialJd),
						inFlight: null
					};
					this.zones.push(state);
					this.prefetchChunkNeighbors(state, state.currentIdx);
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
		} catch (e) {
			console.warn(`zone-refresher: failed to refresh ${z.zone}@${time}:`, e);
		}
	}

	private async loadChunk(z: ChunkZoneState, target: number, date: Date): Promise<void> {
		const previous = z.currentIdx;
		// Optimistic update so a re-entrant tick during the fetch sees this
		// target as already-being-loaded and doesn't double-fire.
		z.currentIdx = target;
		const time = String(target);
		try {
			const chunks = await Promise.all(
				Array.from({ length: z.parts }, (_, part) =>
					this.loader.process(z.zone, z.zoom, part, date, time)
				)
			);

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
			this.prefetchChunkNeighbors(z, target);
		} catch (e) {
			console.warn(`zone-refresher: ${z.zone} chunk reload failed (${previous} → ${target}):`, e);
			z.currentIdx = previous;
		}
	}

	/** Warm the HTTP cache for `[idx-1, idx, idx+1]` (clamped) on a chunk-indexed
	 *  zone so the next boundary crossing in either direction hits a cached
	 *  binary instead of a cold fetch. Past the boundary the J2 secular drift
	 *  extrapolates from a now-invalid epoch, so any fetch latency shows up as
	 *  moons flying off-screen. */
	private prefetchChunkNeighbors(z: ChunkZoneState, idx: number): void {
		const lo = Math.max(0, idx - 1);
		const hi = Math.min(z.zoomData.chunks - 1, idx + 1);
		for (let i = lo; i <= hi; i++) {
			for (let part = 0; part < z.parts; part++) {
				ChunkLoader.prefetch(z.zone, z.zoom, part, String(i));
			}
		}
	}
}
