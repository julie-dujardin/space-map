/**
 * Fetch one probes-payload position file. Probe IDs (`probe-<value>`) ride
 * inside the binary's per-probe header — no sidecar fetch.
 *
 * Zone-level `float64_coeffs` flag is required to size the coefficient reads;
 * the URL also omits the zoom segment per the probes-zone URL convention.
 */

import { parsePosition } from '$lib/fetch/position/parse';
import { chunkedFlatUrl } from '$lib/fetch/position/format';
import type { ProbeChunk } from '$lib/fetch/position/probes/parse';

/**
 * Fetch a gzipped binary, returning `null` for the sparse-zone 404/403 case so
 * the store can cache absence. Other transport errors still throw.
 *
 * Probe zones declare `chunks: total_window_chunks` in the manifest (one slot
 * for every `chunk_years` window across `[start_jd, end_jd]`), but the writer
 * only emits a file for chunks where ≥1 probe contributes. Sparse zones
 * (Pluto, Uranus, Saturn outside the Voyager/Cassini windows, …) therefore
 * have many missing chunk indices. Cloudflare R2 returns 404 on missing keys
 * if a bucket policy allows listing, 403 if it doesn't — both mean "no file".
 */
async function fetchGzBufferOrAbsent(url: string): Promise<ArrayBuffer | null> {
	const res = await fetch(url);
	if (res.status === 404 || res.status === 403) return null;
	if (!res.ok) throw new Error(`Failed to fetch ${url}: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	return new Response(res.body!.pipeThrough(ds)).arrayBuffer();
}

export interface FetchedProbes extends ProbeChunk {
	/** Row index in `probes` → full probe id (mirrors `probes[i].id`). */
	ids: string[];
}

/** Returns the parsed chunk, or `null` when the file isn't present in the
 *  export (sparse-zone gap). Callers must cache the absence so they don't
 *  re-fetch on every `ensure()`. */
export async function fetchProbes(
	zone: string,
	chunk: number,
	float64Coeffs: boolean
): Promise<FetchedProbes | null> {
	const buffer = await fetchGzBufferOrAbsent(chunkedFlatUrl(zone, chunk));
	if (buffer === null) return null;
	const parsed = parsePosition(buffer, { probesFloat64: float64Coeffs });
	if (parsed.kind !== 'probes') {
		throw new Error(`Expected probes payload at ${zone}/${chunk}, got ${parsed.kind}`);
	}
	return { ...parsed.chunk, ids: parsed.chunk.probes.map((p) => p.id) };
}
