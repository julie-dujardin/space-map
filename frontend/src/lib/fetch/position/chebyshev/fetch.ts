/**
 * Fetch one chebyshev-payload position file. Object IDs (`<prefix>-<numeric>`)
 * ride inside the binary's per-body header — no sidecar fetch.
 */

import { parsePosition } from '$lib/fetch/position/parse';
import { chunkedUrl } from '$lib/fetch/position/format';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';
import type { ChebyshevBody, ChebyshevChunk } from '$lib/fetch/position/chebyshev/parse';

async function fetchGzBuffer(url: string): Promise<ArrayBuffer> {
	const res = await fetchWithTimeout(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	return new Response(res.body!.pipeThrough(ds)).arrayBuffer();
}

export interface FetchedChebyshev extends ChebyshevChunk {
	byId: Map<string, ChebyshevBody>;
}

export async function fetchChebyshev(
	zone: string,
	zoom: number | null,
	chunk: number
): Promise<FetchedChebyshev> {
	const buffer = await fetchGzBuffer(chunkedUrl(zone, zoom, chunk));
	const parsed = parsePosition(buffer);
	if (parsed.kind !== 'chebyshev') {
		throw new Error(`Expected chebyshev payload at ${zone}/${chunk}, got ${parsed.kind}`);
	}
	const byId = new Map<string, ChebyshevBody>();
	for (const b of parsed.chunk.bodies) if (b.id) byId.set(b.id, b);
	return { ...parsed.chunk, byId };
}
