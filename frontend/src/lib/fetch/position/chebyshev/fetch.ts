/**
 * Fetch one chebyshev-payload position file. Object IDs (`<prefix>-<numeric>`)
 * ride inside the binary's per-body header — no sidecar fetch.
 */

import { parsePosition } from '$lib/fetch/position/parse';
import { chunkedUrl } from '$lib/fetch/position/format';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';
import type { ChebyshevBody, ChebyshevChunk } from '$lib/fetch/position/chebyshev/parse';

async function fetchGzBuffer(url: string, priority: RequestPriority): Promise<ArrayBuffer> {
	const res = await fetchWithTimeout(url, { priority });
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	return new Response(res.body!.pipeThrough(ds)).arrayBuffer();
}

export interface FetchedChebyshev extends ChebyshevChunk {
	byId: Map<string, ChebyshevBody>;
}

/** `priority` is high for the chunk the first frame waits on, low for a
 *  neighbor warmed behind it. */
export async function fetchChebyshev(
	zone: string,
	zoom: number | null,
	chunk: number,
	priority: RequestPriority
): Promise<FetchedChebyshev> {
	const buffer = await fetchGzBuffer(chunkedUrl(zone, zoom, chunk), priority);
	const parsed = parsePosition(buffer);
	if (parsed.kind !== 'chebyshev') {
		throw new Error(`Expected chebyshev payload at ${zone}/${chunk}, got ${parsed.kind}`);
	}
	const byId = new Map<string, ChebyshevBody>();
	for (const b of parsed.chunk.bodies) if (b.id) byId.set(b.id, b);
	return { ...parsed.chunk, byId };
}
