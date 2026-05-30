/**
 * Hash-bucket point-cloud bodies into subgroups so {@link OrbitWorkerPool}
 * can spread one zone's per-frame Kepler solves across all workers instead of
 * pinning the whole zone to one worker.
 *
 * Splitting only pays off above a minimum bodies-per-bucket — below that the
 * per-Points GPU upload (one `bufferSubData` per worker result) costs more
 * than the parallel-solve savings. Small groups stay as a single bucket
 * routed to a name-hashed worker so they still distribute evenly across the
 * pool without inflating the Points count.
 */

import type { PositionedBody } from '$lib/types/objects';

/**
 * Minimum bodies per bucket for the split path to be worth its overhead.
 * Below `workerCount * MIN_BODIES_PER_BUCKET` total bodies, the group stays
 * unsplit (1 bucket on 1 name-hashed worker).
 *
 * Profiled at 100/200/500/1000/2000 on K=8: 500 is the U-curve sweet spot.
 * Lower (100-200) inflates per-Points GPU upload work on the main thread
 * (rAF median ~2-3 ms vs 0.9 ms at 500); higher (1000-2000) lets medium
 * zones go single-worker and worker spread climbs (~4% at 2000 vs ~1.7% at
 * 500).
 */
export const MIN_BODIES_PER_BUCKET = 600;

function hashString(s: string): number {
	let h = 0;
	for (let i = 0; i < s.length; i++) {
		h = ((h << 5) - h + s.charCodeAt(i)) | 0;
	}
	return h >>> 0;
}

function partitionByHash(bodies: PositionedBody[], k: number): PositionedBody[][] {
	const buckets: PositionedBody[][] = Array.from({ length: k }, () => []);
	for (const b of bodies) {
		buckets[hashString(b.data.id) % k].push(b);
	}
	return buckets;
}

export interface GroupPartition {
	/** Either 1 bucket (small group, no split) or `workerCount` buckets (split). */
	buckets: PositionedBody[][];
	/** Subgroup i should be wired with workerHint `(baseWorker + i) % workerCount`,
	 *  so small unsplit groups distribute across the pool by name hash and big
	 *  split groups span all K workers starting from `baseWorker`. */
	baseWorker: number;
}

/** Partition a zone/parent group's bodies for the worker pool. Caller is
 *  responsible for iterating `workerCount` subgroup slots (not `buckets.length`)
 *  so stale subgroups get unwired when a group crosses the split threshold. */
export function partitionForWorkers(
	name: string,
	bodies: PositionedBody[],
	workerCount: number
): GroupPartition {
	const k = bodies.length >= workerCount * MIN_BODIES_PER_BUCKET ? workerCount : 1;
	return {
		buckets: partitionByHash(bodies, k),
		baseWorker: hashString(name) % workerCount
	};
}

/** Strip the `#i` subgroup suffix added by hash-partitioning to recover the
 *  parent zone or parent-body id (e.g. `mba#3` → `mba`). */
export function parentIdFromSubkey(key: string): string {
	const i = key.indexOf('#');
	return i < 0 ? key : key.substring(0, i);
}
