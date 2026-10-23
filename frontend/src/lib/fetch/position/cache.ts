/**
 * A small LRU of promises. A rejected promise leaves the cache, so the next
 * call tries again. Keep the capacity small: one entry can hold MBs of typed
 * arrays (Earth's position chunk is 5–10 MB).
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
