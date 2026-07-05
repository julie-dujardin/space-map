/**
 * Shared cache for hash-bucketed gzipped-JSON bundles (objects, groups,
 * features), keyed by full URL so the pipelines share it without collision.
 * Rejections evict (like position/cache.ts) so a boot-time blip doesn't poison
 * a URL with no retry; a 404 resolves to `{}` and stays cached.
 */
import { fetchWithTimeout } from './fetch-timeout';

const cache = new Map<string, Promise<Record<string, unknown>>>();

export function fetchGzipBundle<T>(url: string): Promise<Record<string, T>> {
	let p = cache.get(url);
	if (!p) {
		p = (async () => {
			// Timed out: these bundles are on the phase-1 critical path for
			// deep-linked satellites, so a stalled connection can't hang boot.
			const res = await fetchWithTimeout(url);
			if (!res.ok) {
				if (res.status === 404) return {};
				throw new Error(`fetchGzipBundle: ${url} returned ${res.status} ${res.statusText}`);
			}
			const ds = new DecompressionStream('gzip');
			return (await new Response(res.body!.pipeThrough(ds)).json()) as Record<string, unknown>;
		})();
		cache.set(url, p);
		p.catch(() => {
			if (cache.get(url) === p) cache.delete(url);
		});
	}
	return p as Promise<Record<string, T>>;
}
