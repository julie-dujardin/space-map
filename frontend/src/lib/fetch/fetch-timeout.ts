import { loadProgress } from '$lib/scene/state/load-progress.svelte';

/** Longest silence a boot data fetch may have, before its headers or between
 *  two pieces of its body. A stall, not a total: a large chunk on a slow link
 *  that still moves is left to finish. */
export const BOOT_FETCH_TIMEOUT_MS = 30_000;

/**
 * Byte counter for the loading bar, or null where the bar does not count:
 * past boot, without a Content-Length to measure against, and for background
 * prefetches, which nothing waits on.
 */
function bootByteCounter(res: Response, background: boolean): ((bytes: number) => void) | null {
	if (background || !loadProgress.active) return null;
	const total = Number(res.headers.get('content-length'));
	if (!Number.isFinite(total) || total <= 0) return null;
	loadProgress.announce(total);
	return (bytes) => loadProgress.addBytes(bytes);
}

/**
 * `fetch` that aborts when the connection goes silent for `timeoutMs`
 * (default {@link BOOT_FETCH_TIMEOUT_MS}), composing with a caller-supplied
 * `signal`. The watch runs to the end of the body: a caller that reads the
 * response is never left waiting on a dead link. A stall rejects with a plain
 * `Error`, not a bare `AbortError`, so the error UI reads clearly.
 */
export async function fetchWithTimeout(
	input: string | URL,
	init: RequestInit = {},
	timeoutMs = BOOT_FETCH_TIMEOUT_MS
): Promise<Response> {
	const controller = new AbortController();
	let timer: ReturnType<typeof setTimeout> | undefined;
	let stalled = false;
	const arm = () => {
		clearTimeout(timer);
		timer = setTimeout(() => {
			stalled = true;
			controller.abort();
		}, timeoutMs);
	};
	const onCallerAbort = () => controller.abort();
	init.signal?.addEventListener('abort', onCallerAbort, { once: true });
	const release = () => {
		clearTimeout(timer);
		init.signal?.removeEventListener('abort', onCallerAbort);
	};
	const failure = (e: unknown) =>
		stalled ? new Error(`Request stalled for ${timeoutMs} ms: ${input}`, { cause: e }) : e;

	arm();
	let res: Response;
	try {
		res = await fetch(input, { ...init, signal: controller.signal });
	} catch (e) {
		release();
		throw failure(e);
	}
	if (!res.body) {
		release();
		return res;
	}

	const count = bootByteCounter(res, init.priority === 'low');
	const reader = res.body.getReader();
	const body = new ReadableStream<Uint8Array>({
		async pull(out) {
			// Armed only while a read is pending: the time a consumer takes
			// between two reads is not the network's.
			arm();
			try {
				const { done, value } = await reader.read();
				clearTimeout(timer);
				if (done) {
					release();
					out.close();
					return;
				}
				count?.(value.byteLength);
				out.enqueue(value);
			} catch (e) {
				release();
				out.error(failure(e));
			}
		},
		cancel(reason) {
			release();
			return reader.cancel(reason);
		}
	});
	return new Response(body, {
		status: res.status,
		statusText: res.statusText,
		headers: res.headers
	});
}
