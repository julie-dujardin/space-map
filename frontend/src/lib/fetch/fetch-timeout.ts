/** Wall-clock cap for a single boot data fetch. A stalled connection would
 *  otherwise hang the "Loading data" screen forever; aborting lets the caller
 *  surface an error the user can retry. Generous enough for large chunks on a
 *  slow-but-progressing mobile link. */
export const BOOT_FETCH_TIMEOUT_MS = 30_000;

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
		return await fetch(input, { ...init, signal: controller.signal });
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
