/**
 * Tiny LRU cache for parsed-chunk promises. Map insertion order doubles as the
 * access order: a hit deletes-and-re-sets the entry to move it to the tail; a
 * miss appends and the head is dropped when the cache exceeds capacity. Failed
 * promises are removed on rejection so retries don't inherit a poisoned hit.
 *
 * Entries hold the parsed columns (incl. their underlying ArrayBuffers), so
 * keep capacity modest — Earth's ~25K-row chunk parses to ~5–10 MB of typed
 * arrays. The cache trades memory for re-parse cost when the same snapshot is
 * fetched again (hot-reload scrubbing across snapshot boundaries).
 */
export class LruPromiseCache<V> {
	private readonly map = new Map<string, Promise<V>>();
	constructor(private readonly capacity: number) {}

	getOrCompute(key: string, compute: () => Promise<V>): Promise<V> {
		const cached = this.map.get(key);
		if (cached) {
			this.map.delete(key);
			this.map.set(key, cached);
			return cached;
		}
		const p = compute();
		this.map.set(key, p);
		if (this.map.size > this.capacity) {
			const oldest = this.map.keys().next().value;
			if (oldest !== undefined) this.map.delete(oldest);
		}
		p.catch(() => {
			if (this.map.get(key) === p) this.map.delete(key);
		});
		return p;
	}
}
