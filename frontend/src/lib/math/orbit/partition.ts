/**
 * Hash-bucket point-cloud bodies into subgroups so {@link OrbitWorkerPool}
 * spreads one zone's per-frame Kepler solves across all workers, not just one.
 * Splitting only pays off above a minimum bodies-per-bucket — below that the
 * per-Points GPU upload costs more than the parallel-solve saves, so small
 * groups stay a single bucket on a name-hashed worker.
 */

import type { PositionedBody } from '$lib/types/objects';
import { yieldToMain } from '$lib/yield';

/**
 * Minimum bodies per bucket for splitting to be worth its overhead. Below
 * `workerCount * MIN_BODIES_PER_BUCKET`, the group stays unsplit (1 bucket,
 * 1 name-hashed worker).
 *
 * Profiled at 100/200/500/1000/2000 on K=8: 500 is the U-curve sweet spot —
 * lower inflates GPU upload (rAF ~2-3ms vs 0.9ms), higher pushes medium
 * zones single-worker and worsens spread (~4% vs ~1.7%).
 */
export const MIN_BODIES_PER_BUCKET = 600;

/** Stable 32-bit string hash (djb2-ish). Used for both body→bucket assignment
 *  and group-name→baseWorker spread. */
export function hashString(s: string): number {
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
	/** Subgroup i wires to workerHint `(baseWorker + i) % workerCount` — unsplit
	 *  groups spread by name hash; split groups span all K workers from `baseWorker`. */
	baseWorker: number;
}

/** Partition a zone/parent group's bodies for the worker pool. Caller must
 *  iterate `workerCount` slots, not `buckets.length`, so stale subgroups
 *  unwire when a group crosses the split threshold. */
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

/** Time-budgeted {@link partitionForWorkers} for the streaming rebuild path —
 *  hashing >1M ids in one go blocks for >100ms. */
export async function partitionForWorkersSliced(
	name: string,
	bodies: PositionedBody[],
	workerCount: number
): Promise<GroupPartition> {
	const k = bodies.length >= workerCount * MIN_BODIES_PER_BUCKET ? workerCount : 1;
	const buckets: PositionedBody[][] = Array.from({ length: k }, () => []);
	let sliceStart = performance.now();
	for (let i = 0; i < bodies.length; i++) {
		if ((i & 16383) === 16383 && performance.now() - sliceStart > 6) {
			await yieldToMain();
			sliceStart = performance.now();
		}
		const b = bodies[i];
		buckets[hashString(b.data.id) % k].push(b);
	}
	return { buckets, baseWorker: hashString(name) % workerCount };
}

/** Strip the `#i` subgroup suffix added by hash-partitioning to recover the
 *  parent zone or parent-body id (e.g. `mba#3` → `mba`). */
export function parentIdFromSubkey(key: string): string {
	const i = key.indexOf('#');
	return i < 0 ? key : key.substring(0, i);
}
