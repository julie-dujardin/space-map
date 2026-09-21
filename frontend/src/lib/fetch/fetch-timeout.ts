import { loadProgress } from '$lib/scene/state/load-progress.svelte';

/** Wall-clock cap for a boot data fetch — aborting lets the caller surface a
 *  retryable error instead of hanging "Loading data" forever. Generous
 *  enough for large chunks on a slow-but-progressing mobile link. */
export const BOOT_FETCH_TIMEOUT_MS = 30_000;

/**
 * Tee the compressed response through a byte counter so the loading bar
 * reflects real download activity. Skipped past boot, without a
 * Content-Length to measure against, or for background prefetches — the bar
 * measures the map coming up, and nothing waits on those.
 */
function countBootBytes(res: Response, background: boolean): Response {
	if (background || !loadProgress.active || !res.body) return res;
	const total = Number(res.headers.get('content-length'));
	if (!Number.isFinite(total) || total <= 0) return res;
	loadProgress.announce(total);
	const counter = new TransformStream<Uint8Array, Uint8Array>({
		transform(chunk, controller) {
			loadProgress.addBytes(chunk.byteLength);
			controller.enqueue(chunk);
		}
	});
	return new Response(res.body.pipeThrough(counter), {
		status: res.status,
		statusText: res.statusText,
		headers: res.headers
	});
}

/**
 * `fetch` that aborts after `timeoutMs` (default {@link BOOT_FETCH_TIMEOUT_MS}),
 * composing with a caller-supplied `signal`. Timeout rejects with a plain
 * `Error`, not a bare `AbortError`, so boot error UI reads clearly.
 */
export async function fetchWithTimeout(
	input: string | URL,
	init: RequestInit = {},
	timeoutMs = BOOT_FETCH_TIMEOUT_MS
): Promise<Response> {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), timeoutMs);
	const onCallerAbort = () => controller.abort();
	init.signal?.addEventListener('abort', onCallerAbort, { once: true });
	try {
		const res = await fetch(input, { ...init, signal: controller.signal });
		return countBootBytes(res, init.priority === 'low');
	} catch (e) {
		if (controller.signal.aborted && !init.signal?.aborted) {
			throw new Error(`Request timed out after ${timeoutMs} ms: ${input}`, { cause: e });
		}
		throw e;
	} finally {
		clearTimeout(timer);
		init.signal?.removeEventListener('abort', onCallerAbort);
	}
}
