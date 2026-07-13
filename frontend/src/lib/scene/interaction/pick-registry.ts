/**
 * Maps a GPU pick-pass's decoded pick-id back to a body id.
 *
 * Each worker group is assigned a contiguous pick-id range `[base, base + len)`
 * at wire time; row `r` of the group gets pick-id `base + r`, which the worker
 * writes into the compact pick-id buffer (see {@link writePositions}). The
 * renderer reads a pick-id off the framebuffer and calls {@link resolve} to get
 * the body id.
 *
 * Pick-ids are a monotonic bump counter (never reused within a session) so a
 * stale framebuffer read after a repack resolves to nothing rather than the
 * wrong body. The 32-bit space is ample for a session; a page reload resets it.
 */
export class PickRegistry {
	#next = 1; // 0 is reserved for "no hit" (cleared framebuffer)
	readonly #groups = new Map<string, { base: number; ids: readonly string[] }>();

	/** Assign `ids` a fresh pick-id range and return its base. Replaces any prior
	 *  range for `groupId` (a repack), dropping the old ids. */
	allocate(groupId: string, ids: readonly string[]): number {
		const base = this.#next;
		this.#next += ids.length;
		this.#groups.set(groupId, { base, ids });
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
		for (const { base, ids } of this.#groups.values()) {
			if (pickId >= base && pickId < base + ids.length) {
				const id = ids[pickId - base];
				return id === '' ? null : id;
			}
		}
		return null;
	}

	clear(): void {
		this.#groups.clear();
		this.#next = 1;
	}
}
