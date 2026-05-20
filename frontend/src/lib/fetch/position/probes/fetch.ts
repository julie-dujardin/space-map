/**
 * Fetch one probes-payload position file. Probe IDs (`probe-<value>`) ride
 * inside the binary's per-probe header — no sidecar fetch.
 *
 * Zone-level `float64_coeffs` flag is required to size the coefficient reads;
 * the URL also omits the zoom segment per the probes-zone URL convention.
 *
 * Sparse-zone gaps (chunks with no file on the export) are filtered upstream
 * by the `ProbeStore` via the manifest's `present` ranges — every URL we
 * issue here is expected to resolve, so any 404/403 indicates a stale
 * manifest and is surfaced as a thrown error.
 */

import { parsePosition } from '$lib/fetch/position/parse';
import { chunkedFlatUrl } from '$lib/fetch/position/format';
import type { ProbeChunk } from '$lib/fetch/position/probes/parse';

export interface FetchedProbes extends ProbeChunk {
	/** Row index in `probes` → full probe id (mirrors `probes[i].id`). */
	ids: string[];
}

export async function fetchProbes(
	zone: string,
	chunk: number,
	float64Coeffs: boolean
): Promise<FetchedProbes> {
	const url = chunkedFlatUrl(zone, chunk);
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	const buffer = await new Response(res.body!.pipeThrough(ds)).arrayBuffer();
	const parsed = parsePosition(buffer, { probesFloat64: float64Coeffs });
	if (parsed.kind !== 'probes') {
		throw new Error(`Expected probes payload at ${zone}/${chunk}, got ${parsed.kind}`);
	}
	return { ...parsed.chunk, ids: parsed.chunk.probes.map((p) => p.id) };
}
