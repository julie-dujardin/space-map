/**
 * Primitives for the gzipped-JSON files of the data export.
 *
 * Memos evict on rejection: the export is static, so a retry is the only way
 * back from a transient failure, and a kept rejection would leave the feature
 * dead for the whole session.
 */

/** Decode a gzipped JSON response body. */
export async function gunzipJson<T>(res: Response): Promise<T> {
	const ds = new DecompressionStream('gzip');
	return (await new Response(res.body!.pipeThrough(ds)).json()) as T;
}

export interface GzJsonOptions<T> {
	/** Value for a 404. Absent means a 404 throws like any other bad status —
	 *  the policy differs per file, so each call site states its own. */
	onMissing?: () => T;
	/** Defaults to plain `fetch`; pass `fetchWithTimeout` for boot-path files. */
	fetcher?: (url: string) => Promise<Response>;
	/** Message text for a bad status. */
	error?: (res: Response, url: string) => string;
}

/**
 * Load a gzipped JSON file once per session, sharing the in-flight promise.
 * `url` is a thunk because data URLs carry a version token that only exists
 * after metadata resolves; it may await that itself.
 */
export function memoizedGzJson<T>(
	url: () => string | Promise<string>,
	opts: GzJsonOptions<T> = {}
): () => Promise<T> {
	const {
		onMissing,
		fetcher = (u: string) => fetch(u),
		error = (res, u) => `memoizedGzJson: ${u} returned ${res.status} ${res.statusText}`
	} = opts;
	let pending: Promise<T> | null = null;
	return () => {
		if (pending) return pending;
		const p = (async () => {
			const resolved = await url();
			const res = await fetcher(resolved);
			if (!res.ok) {
				if (res.status === 404 && onMissing) return onMissing();
				throw new Error(error(res, resolved));
			}
			return gunzipJson<T>(res);
		})();
		pending = p;
		p.catch(() => {
			if (pending === p) pending = null;
		});
		return p;
	};
}
