/**
 * Fetch one chebyshev-payload position file. Object IDs (`<prefix>-<numeric>`)
 * ride inside the binary's per-body header — no sidecar fetch.
 */

import { parsePosition } from '$lib/fetch/position/parse';
import { chunkedUrl } from '$lib/fetch/position/format';
import type { ChebyshevChunk } from '$lib/fetch/position/chebyshev/parse';

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
	const buffer = await fetchGzBuffer(chunkedUrl(zone, 0, chunk));
	const parsed = parsePosition(buffer);
	if (parsed.kind !== 'chebyshev') {
		throw new Error(`Expected chebyshev payload at ${zone}/0/${chunk}, got ${parsed.kind}`);
	}
	return { ...parsed.chunk, ids: parsed.chunk.bodies.map((b) => b.id) };
}
