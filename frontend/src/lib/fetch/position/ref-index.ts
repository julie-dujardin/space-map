import type { ObjectKey } from '$lib/fetch/position/object-key';

const INITIAL_SLOTS = 1 << 12;
/** Linear probing stays cheap below this; a probe re-derives its key from
 *  the row, so long runs cost more than in a table that stores keys. */
const MAX_LOAD = 0.75;

/** Keys reach 2^40 (spkid × 8), so fold the high word in before mixing. */
function hashKey(key: ObjectKey): number {
	let h = (key ^ Math.floor(key / 4294967296)) >>> 0;
	h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
	h = Math.imul(h ^ (h >>> 16), 0x45d9f3b);
	return (h ^ (h >>> 16)) >>> 0;
}

/**
 * Open-addressing index from {@link ObjectKey} to a row reference for the
 * million-row asteroid buckets. A `Map` costs tens of bytes per entry there;
 * this holds one uint32 per slot and rebuilds a slot's key from its row when
 * probing instead of storing it. Never shrinks; rows are never removed.
 */
export class RefIndex {
	/** `ref + 1` per slot, 0 = empty. */
	private table = new Uint32Array(INITIAL_SLOTS);
	private mask = INITIAL_SLOTS - 1;
	private count = 0;

	constructor(private readonly keyOfRef: (ref: number) => ObjectKey) {}

	get size(): number {
		return this.count;
	}

	/** Slot holding `key`, or the empty slot where it would go. */
	private slot(key: ObjectKey): number {
		let i = hashKey(key) & this.mask;
		for (;;) {
			const v = this.table[i];
			if (v === 0 || this.keyOfRef(v - 1) === key) return i;
			i = (i + 1) & this.mask;
		}
	}

	get(key: ObjectKey): number | undefined {
		const v = this.table[this.slot(key)];
		return v === 0 ? undefined : v - 1;
	}

	has(key: ObjectKey): boolean {
		return this.table[this.slot(key)] !== 0;
	}

	/**
	 * Store `ref` under `key`; an existing entry is overwritten only when
	 * `replace(prev)` says so. Returns true when the key was new.
	 */
	set(key: ObjectKey, ref: number, replace: (prev: number) => boolean = () => true): boolean {
		let i = this.slot(key);
		const v = this.table[i];
		if (v !== 0) {
			if (replace(v - 1)) this.table[i] = ref + 1;
			return false;
		}
		this.count++;
		if (this.count > this.table.length * MAX_LOAD) {
			this.grow();
			i = this.slot(key);
		}
		this.table[i] = ref + 1;
		return true;
	}

	private grow(): void {
		const old = this.table;
		this.table = new Uint32Array(old.length * 2);
		this.mask = this.table.length - 1;
		for (const v of old) {
			if (v === 0) continue;
			let i = hashKey(this.keyOfRef(v - 1)) & this.mask;
			while (this.table[i] !== 0) i = (i + 1) & this.mask;
			this.table[i] = v;
		}
	}

	*values(): IterableIterator<number> {
		for (const v of this.table) if (v !== 0) yield v - 1;
	}

	*keys(): IterableIterator<ObjectKey> {
		for (const ref of this.values()) yield this.keyOfRef(ref);
	}
}
