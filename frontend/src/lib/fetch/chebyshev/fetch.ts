/**
 * Fetch one chebyshev chunk: the binary polynomials plus the sidecar id list
 * that maps body-table row index → object id (`<source>-<numeric>` convention).
 */

import { chebyshevBinUrl, chebyshevIdsUrl } from '$lib/fetch/chebyshev/constants';
import { parseChebyshev, type ChebyshevChunk } from '$lib/fetch/chebyshev/parse';

async function fetchGzBuffer(url: string): Promise<ArrayBuffer> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	return new Response(res.body!.pipeThrough(ds)).arrayBuffer();
}

async function fetchGzText(url: string): Promise<string> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	return new Response(res.body!.pipeThrough(ds)).text();
}

export interface FetchedChebyshev extends ChebyshevChunk {
	/** Row index in `bodies` → full object id (matches elements `.id.gz`). */
	ids: string[];
}

export async function fetchChebyshev(zone: string, chunk: number): Promise<FetchedChebyshev> {
	const [buffer, idsText] = await Promise.all([
		fetchGzBuffer(chebyshevBinUrl(zone, chunk)),
		fetchGzText(chebyshevIdsUrl(zone, chunk))
	]);
	const parsed = parseChebyshev(buffer);
	const ids = idsText.split('\n');
	if (ids.length !== parsed.bodies.length) {
		throw new Error(
			`chebyshev ${zone}/${chunk}: ids (${ids.length}) and bodies (${parsed.bodies.length}) length mismatch`
		);
	}
	return { ...parsed, ids };
}
