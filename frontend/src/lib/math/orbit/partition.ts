/**
 * Hash-bucket point-cloud bodies into K subgroups so {@link OrbitWorkerPool}
 * can spread one zone's per-frame Kepler solves across all workers instead of
 * pinning the whole zone to one worker. Each subgroup ends up as its own
 * `Points` object + group; the pool's round-robin (or explicit workerHint)
 * places subgroup #i on worker `i % K`.
 */

import type { PositionedBody } from '$lib/types/objects';

function hashId(s: string): number {
	let h = 0;
	for (let i = 0; i < s.length; i++) {
		h = ((h << 5) - h + s.charCodeAt(i)) | 0;
	}
	return h >>> 0;
}

export function partitionByHash(bodies: PositionedBody[], k: number): PositionedBody[][] {
	const buckets: PositionedBody[][] = Array.from({ length: k }, () => []);
	for (const b of bodies) {
		buckets[hashId(b.data.id) % k].push(b);
	}
	return buckets;
}

/** Strip the `#i` subgroup suffix added by hash-partitioning to recover the
 *  parent zone or parent-body id (e.g. `mba#3` → `mba`). */
export function parentIdFromSubkey(key: string): string {
	const i = key.indexOf('#');
	return i < 0 ? key : key.substring(0, i);
}
