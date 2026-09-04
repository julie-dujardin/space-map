import { keyToId, type ObjectKey } from '$lib/fetch/position/object-key';

/**
 * Maps a GPU pick-pass's decoded pick-id back to a body id. Each worker group
 * gets a contiguous pick-id range `[base, base + len)`; row `r` gets `base + r`.
 *
 * Ids are a monotonic bump counter, never reused within a session, so a stale
 * framebuffer read after a repack resolves to nothing rather than the wrong body.
 */
export class PickRegistry {
	#next = 1; // 0 is reserved for "no hit" (cleared framebuffer)
	readonly #groups = new Map<string, { base: number; keys: ArrayLike<ObjectKey> }>();

	/** Assign `keys` (one per row, `NO_KEY` for a skipped row) a fresh pick-id
	 *  range and return its base. Replaces any prior range for `groupId` (a
	 *  repack), dropping the old keys. */
	allocate(groupId: string, keys: ArrayLike<ObjectKey>): number {
		const base = this.#next;
		this.#next += keys.length;
		this.#groups.set(groupId, { base, keys });
		return base;
	}

	/** Drop a group's range (its cloud was unwired). */
	release(groupId: string): void {
		this.#groups.delete(groupId);
	}

	/** Body id for a decoded pick-id, or null if it belongs to no live range
	 *  (stale read) or lands on a skipped row. Linear over the group set, which
	 *  is small (~zones × workers + spacecraft groups). */
	resolve(pickId: number): string | null {
		if (pickId === 0) return null;
		for (const { base, keys } of this.#groups.values()) {
			if (pickId >= base && pickId < base + keys.length) return keyToId(keys[pickId - base]);
		}
		return null;
	}

	clear(): void {
		this.#groups.clear();
		this.#next = 1;
	}
}
