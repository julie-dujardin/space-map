import { loadProgress } from '$lib/scene/state/load-progress.svelte';

/** Wall-clock cap for a single boot data fetch. A stalled connection would
 *  otherwise hang the "Loading data" screen forever; aborting lets the caller
 *  surface an error the user can retry. Generous enough for large chunks on a
 *  slow-but-progressing mobile link. */
export const BOOT_FETCH_TIMEOUT_MS = 30_000;

/**
 * Tee the compressed response stream through a byte counter so the loading bar
 * reflects real download activity. Skipped past boot (`active` false) or without
 * a Content-Length to fill the gap against. Callers still decompress the body.
 */
function countBootBytes(res: Response): Response {
	if (!loadProgress.active || !res.body) return res;
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
 * `fetch` that aborts after `timeoutMs` (default {@link BOOT_FETCH_TIMEOUT_MS}).
 * Composes with a caller-supplied `signal`, so focus-change cancellation still
 * works. On timeout the rejection is a plain `Error` (not a bare `AbortError`)
 * so boot error UI reads clearly.
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
		return countBootBytes(await fetch(input, { ...init, signal: controller.signal }));
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
