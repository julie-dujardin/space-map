/**
 * Per-zone cache of Chebyshev chunks, from binaries at
 * `/data/v1/position/{zone}/[0/]{chunkIdx}.bin.gz`. Each chunked zone
 * declares its own `chunks`/`chunk_days`/`start_jd` — Saturn's ~46-day
 * cadence and Pluto's ~730-day cadence coexist with no global tier metadata;
 * chunk index for a JD is `floor((jd - start_jd) / chunk_days)`.
 *
 * Chunk loading is the shared {@link ChunkWindow}; this adds the query surface
 * over the resident chunks. Bodies are keyed by full object id
 * (`<prefix>-<numeric>`).
 */

import { fetchChebyshev, type FetchedChebyshev } from '$lib/fetch/position/chebyshev/fetch';
import { chebyshevPositionScene } from '$lib/fetch/position/chebyshev/propagate';
import type { ChebyshevBody } from '$lib/fetch/position/chebyshev/parse';
import { chunkIndexForJd } from '$lib/fetch/metadata';
import { ChunkWindow } from '$lib/fetch/position/chunk-window';

/** Walk the chunk for jd in every loaded zone and yield each body alongside
 *  the chunk's validity window (used by callers that build PositionedBody).
 *  Bodies whose chunk hasn't loaded yet are skipped — caller is responsible
 *  for awaiting `ensure(jd).done` first. */
export interface BodyWithWindow {
	zone: string;
	body: ChebyshevBody;
	startJd: number;
	endJd: number;
}

/** Per-zone chebyshev params from the manifest's chunked entry. `zoom` is the
 *  URL segment: 0 for the multi-zoom `major` zone, null for flat zones. */
export interface ChebyshevZoneParams {
	zoom: number | null;
	chunks: number;
	chunk_days: number;
	start_jd: number;
	end_jd: number;
}

interface BodyLocation {
	zone: string;
	chunkIdx: number;
	body: ChebyshevBody;
}

export class ChebyshevStore extends ChunkWindow<FetchedChebyshev, ChebyshevZoneParams> {
	/** `objectId → zone` so a position query routes without scanning zones. */
	private readonly idToZone = new Map<string, string>();

	/** Every chunk of a chebyshev zone ships. */
	protected isLoadable(): boolean {
		return true;
	}

	protected fetchChunk(
		zone: string,
		params: ChebyshevZoneParams,
		chunkIdx: number,
		priority: RequestPriority
	): Promise<FetchedChebyshev> {
		return fetchChebyshev(zone, params.zoom, chunkIdx, priority);
	}

	protected afterStore(zone: string, chunk: FetchedChebyshev): void {
		for (const id of chunk.byId.keys()) {
			// Multiple chunks list the same body; zone assignment is stable across
			// chunks by construction (same writer partitions). First write wins.
			if (!this.idToZone.has(id)) this.idToZone.set(id, zone);
		}
	}

	has(objectId: string): boolean {
		return this.idToZone.has(objectId);
	}

	/**
	 * Full JD extent of the zone hosting `objectId` — union of all its chunks.
	 * Distinguishes "jd permanently outside exported coverage" (notice-worthy)
	 * from "chunk still loading" (transient). Returns null if the body isn't
	 * tracked or its zone hasn't been seen yet.
	 */
	zoneCoverage(objectId: string): { start: number; end: number } | null {
		const zone = this.idToZone.get(objectId);
		if (zone === undefined) return null;
		const params = this.zoneParams.get(zone);
		if (!params) return null;
		return { start: params.start_jd, end: params.end_jd };
	}

	private resolve(objectId: string, jd: number): BodyLocation | null {
		const zone = this.idToZone.get(objectId);
		if (zone === undefined) return null;
		const params = this.zoneParams.get(zone);
		if (!params) return null;
		const chunkIdx = chunkIndexForJd(params, jd);
		const zoneMap = this.chunks.get(zone);
		const chunk = zoneMap?.get(chunkIdx);
		if (!chunk) return null;
		const body = chunk.byId.get(objectId);
		if (!body) return null;
		return { zone, chunkIdx, body };
	}

	/**
	 * Look up the parsed body record for `objectId` at `jd` — used by code
	 * paths that need the body header (`hasLocalized`, `radiusKm`, …) in
	 * addition to the position.
	 */
	body(objectId: string, jd: number): ChebyshevBody | null {
		return this.resolve(objectId, jd)?.body ?? null;
	}

	/**
	 * Iterate every chebyshev body covered by `jd` across every zone. Skips
	 * zones whose chunk for `jd` isn't loaded yet (callers must await
	 * `ensure(jd).done` to guarantee full coverage). Used by the scene loader
	 * to construct the major-body list — every Sun/planet/dwarf/perturber/
	 * whitelisted moon comes through here; chebyshev is their only position
	 * source.
	 */
	*bodiesAt(jd: number): IterableIterator<BodyWithWindow> {
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			for (const body of chunk.bodies) {
				yield { zone, body, startJd: chunk.startJd, endJd: chunk.endJd };
			}
		}
	}

	/**
	 * Parent-relative position in Three.js scene units at `jd`. Returns null if
	 * the body isn't chebyshev-backed, its chunk isn't loaded, or `jd` is
	 * outside segment coverage.
	 */
	positionScene(objectId: string, jd: number): [number, number, number] | null {
		const loc = this.resolve(objectId, jd);
		if (!loc) return null;
		return chebyshevPositionScene(loc.body, jd);
	}
}
