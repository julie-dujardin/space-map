import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';

const TIMEOUT_MS = 1000;
const encode = (text: string) => new TextEncoder().encode(text);

/** A `fetch` whose headers and body pieces arrive when the test says so, and
 *  which dies with its signal the way the real one does. */
function stubFetch() {
	let sendHeaders!: () => void;
	let body!: ReadableStreamDefaultController<Uint8Array>;
	const stream = new ReadableStream<Uint8Array>({
		start(controller) {
			body = controller;
		}
	});
	const fetchMock = vi.fn((_input: string | URL, init?: RequestInit) => {
		const signal = init!.signal!;
		return new Promise<Response>((resolve, reject) => {
			const abort = () => {
				const error = new DOMException('aborted', 'AbortError');
				reject(error);
				try {
					body.error(error);
				} catch {
					// The body is closed.
				}
			};
			signal.addEventListener('abort', abort, { once: true });
			sendHeaders = () => resolve(new Response(stream));
		});
	});
	vi.stubGlobal('fetch', fetchMock);
	return {
		sendHeaders: () => sendHeaders(),
		send: (text: string) => body.enqueue(encode(text)),
		end: () => body.close()
	};
}

describe('fetchWithTimeout', () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	it('rejects when the headers do not arrive', async () => {
		stubFetch();
		const res = fetchWithTimeout('/data/x', {}, TIMEOUT_MS);
		const outcome = expect(res).rejects.toThrow('Request stalled for 1000 ms: /data/x');
		await vi.advanceTimersByTimeAsync(TIMEOUT_MS);
		await outcome;
	});

	it('rejects the body read when the body stops after the headers', async () => {
		const net = stubFetch();
		const pending = fetchWithTimeout('/data/x', {}, TIMEOUT_MS);
		net.sendHeaders();
		const res = await pending;
		net.send('first');
		const text = res.text();
		const outcome = expect(text).rejects.toThrow('Request stalled for 1000 ms: /data/x');
		await vi.advanceTimersByTimeAsync(TIMEOUT_MS);
		await outcome;
	});

	it('lets a slow body finish while it still moves', async () => {
		const net = stubFetch();
		const pending = fetchWithTimeout('/data/x', {}, TIMEOUT_MS);
		net.sendHeaders();
		const res = await pending;
		const text = res.text();
		// Three times the timeout in all, never silent for the whole of one.
		for (const piece of ['a', 'b', 'c', 'd']) {
			await vi.advanceTimersByTimeAsync(TIMEOUT_MS * 0.75);
			net.send(piece);
		}
		net.end();
		await expect(text).resolves.toBe('abcd');
	});

	it('does not time a consumer that reads late', async () => {
		const net = stubFetch();
		const pending = fetchWithTimeout('/data/x', {}, TIMEOUT_MS);
		net.sendHeaders();
		const res = await pending;
		net.send('whole');
		net.end();
		await vi.advanceTimersByTimeAsync(TIMEOUT_MS * 5);
		await expect(res.text()).resolves.toBe('whole');
	});

	it('passes the abort of the caller through as it is', async () => {
		stubFetch();
		const caller = new AbortController();
		const res = fetchWithTimeout('/data/x', { signal: caller.signal }, TIMEOUT_MS);
		const outcome = expect(res).rejects.toMatchObject({ name: 'AbortError' });
		caller.abort();
		await outcome;
	});
});
