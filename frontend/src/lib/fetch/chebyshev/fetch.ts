/**
 * Fetch one chebyshev chunk. Object IDs (`<prefix>-<numeric>`) ride inside the
 * binary's per-body header — no sidecar fetch.
 */

import { chebyshevBinUrl } from '$lib/fetch/chebyshev/constants';
import { parseChebyshev, type ChebyshevChunk } from '$lib/fetch/chebyshev/parse';

async function fetchGzBuffer(url: string): Promise<ArrayBuffer> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	return new Response(res.body!.pipeThrough(ds)).arrayBuffer();
}

export interface FetchedChebyshev extends ChebyshevChunk {
	/** Row index in `bodies` → full object id (mirrors `bodies[i].id`). */
	ids: string[];
}

export async function fetchChebyshev(zone: string, chunk: number): Promise<FetchedChebyshev> {
	const buffer = await fetchGzBuffer(chebyshevBinUrl(zone, chunk));
	const parsed = parseChebyshev(buffer);
	return { ...parsed, ids: parsed.bodies.map((b) => b.id) };
}
