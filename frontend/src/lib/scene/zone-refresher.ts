/**
 * Hot-reload driver for time-segmented zones (currently only `earth`). Watches
 * the sim clock and, when the desired snapshot date for a zone diverges from
 * the loaded one, refetches that zone's chunks and reconciles them into the
 * ContextManager's per-zone body buckets.
 *
 * Throttle: at most one load in flight, and at most one load *started* per
 * `MIN_LOAD_INTERVAL_MS`. Latest-target-wins is implicit — `tick()` recomputes
 * the desired snapshot every call, so whatever date the user has scrubbed to
 * by the time the slot opens is what gets loaded.
 *
 * Step 1 only handles spacecraft buckets (`spacecraftByParent`), because the
 * only time-segmented zone today is `earth` and it ships SGP4 satellites. The
 * code paths for asteroid zones are left as TODOs.
 */

import { ObjectType, type PositionedBody } from '$lib/types/objects';
import {
	isTimeSegmented,
	snapshotDate,
	type Metadata,
	type TimeSegmentedZoom
} from '$lib/fetch/metadata';
import type { ChunkLoader } from '$lib/fetch/elements/chunk';
import type { ContextManager } from '$lib/scene/context-manager.svelte';

const MIN_LOAD_INTERVAL_MS = 2000;

interface ZoneState {
	zone: string;
	zoom: number;
	parts: number;
	zoomData: TimeSegmentedZoom;
	/** Snapshot date string of the currently loaded data. */
	currentTime: string;
	/** Bucket keys this zone wrote into on the last load — used to clean up
	 *  buckets that vanish in a newer snapshot. Empty until the first refresh. */
	knownBuckets: Set<string>;
}

export class ZoneRefresher {
	private readonly zones: ZoneState[] = [];
	private inFlight: Promise<void> | null = null;
	private lastLoadStartMs = -Infinity;

	constructor(
		private readonly ctx: ContextManager,
		metadata: Metadata,
		private readonly loader: ChunkLoader,
		initialDate: Date
	) {
		for (const [zone, zoneData] of Object.entries(metadata.zones)) {
			for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms)) {
				if (!isTimeSegmented(zoomData)) continue;
				this.zones.push({
					zone,
					zoom: Number(zoomStr),
					parts: Math.min(zoomData.parts, 20),
					zoomData,
					currentTime: snapshotDate(zoomData, initialDate),
					knownBuckets: new Set()
				});
			}
		}
	}

	/** Call from the renderer's per-frame loop on jd change. Cheap when nothing
	 *  needs reloading: a couple of date ops and string compares. */
	tick(date: Date): void {
		if (this.inFlight) return;
		const nowMs = performance.now();
		if (nowMs - this.lastLoadStartMs < MIN_LOAD_INTERVAL_MS) return;

		for (const z of this.zones) {
			const target = snapshotDate(z.zoomData, date);
			if (target === z.currentTime) continue;
			this.lastLoadStartMs = nowMs;
			this.inFlight = this.load(z, target, date).finally(() => {
				this.inFlight = null;
			});
			return;
		}
	}

	private async load(z: ZoneState, time: string, date: Date): Promise<void> {
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
}
