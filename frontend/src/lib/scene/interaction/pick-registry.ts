import { keyToId, type ObjectKey } from '$lib/fetch/position/object-key';

/** A row of a range whose owner names its object. */
export interface PickRow {
	groupId: string;
	row: number;
}

interface PickGroup {
	groupId: string;
	base: number;
	length: number;
	/** One key per row, or null when the owner resolves its rows. */
	keys: ArrayLike<ObjectKey> | null;
}

/**
 * Maps a GPU pick-pass's decoded pick-id back to what was drawn. Each group
 * gets a contiguous pick-id range `[base, base + length)`; row `r` gets
 * `base + r`.
 *
 * A worker group carries a key per row, so its pick-id resolves to a body id.
 * A star node cannot: an ObjectKey holds a 32-bit number and a star ID is up to
 * 2^53, and a node's IDs load only on a click in it. Its range resolves to the
 * row, and the starfield reads the ID from the node's ID file.
 *
 * Ids are a monotonic bump counter, never reused within a session, so a stale
 * framebuffer read after a repack resolves to nothing rather than the wrong body.
 */
export class PickRegistry {
	#next = 1; // 0 is reserved for "no hit" (cleared framebuffer)
	readonly #groups = new Map<string, PickGroup>();

	/** Assign `keys` (one per row, `NO_KEY` for a skipped row) a fresh pick-id
	 *  range and return its base. Replaces any prior range for `groupId` (a
	 *  repack), dropping the old keys. */
	allocate(groupId: string, keys: ArrayLike<ObjectKey>): number {
		return this.add(groupId, keys.length, keys);
	}

	/** A fresh range of `length` rows that its owner resolves with
	 *  {@link locate}. */
	allocateRows(groupId: string, length: number): number {
		return this.add(groupId, length, null);
	}

	private add(groupId: string, length: number, keys: ArrayLike<ObjectKey> | null): number {
		const base = this.#next;
		this.#next += length;
		this.#groups.set(groupId, { groupId, base, length, keys });
		return base;
	}

	/** Drop a group's range (its cloud was unwired). */
	release(groupId: string): void {
		this.#groups.delete(groupId);
	}

	/** Body id for a decoded pick-id, or null if it belongs to no live keyed
	 *  range (stale read) or lands on a skipped row. Linear over the group set,
	 *  which is small (~zones × workers + spacecraft groups + picked star
	 *  nodes). */
	resolve(pickId: number): string | null {
		const group = this.find(pickId);
		if (!group?.keys) return null;
		return keyToId(group.keys[pickId - group.base]);
	}

	/** The group and row of a decoded pick-id in a range from
	 *  {@link allocateRows}, or null. */
	locate(pickId: number): PickRow | null {
		const group = this.find(pickId);
		if (!group || group.keys) return null;
		return { groupId: group.groupId, row: pickId - group.base };
	}

	private find(pickId: number): PickGroup | null {
		for (const group of this.#groups.values()) {
			if (pickId >= group.base && pickId < group.base + group.length) return group;
		}
		return null;
	}

	clear(): void {
		this.#groups.clear();
		this.#next = 1;
	}
}
