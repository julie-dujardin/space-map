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
import { ChunkWindow, chunkKey } from '$lib/fetch/position/chunk-window';
import type { CoverageWindow } from '$lib/fetch/coverage';
import { tdbToUtc, utcToTdb } from '$lib/time/jd';

/** The date of `spans` nearest `tdb`, a little inside so it falls in a chunk
 *  that holds the body. */
function nearestInside(spans: [number, number][], tdb: number): number {
	let best = NaN;
	let bestDistance = Infinity;
	for (const [a, b] of spans) {
		const inset = Math.min(1, (b - a) / 2);
		for (const edge of [a + inset, b - inset]) {
			const distance = Math.abs(edge - tdb);
			if (distance < bestDistance) {
				best = edge;
				bestDistance = distance;
			}
		}
	}
	return best;
}

/** True when one of `spans` reaches into `[start, end)`. */
function overlaps(spans: readonly [number, number][], start: number, end: number): boolean {
	return spans.some(([a, b]) => a < end && b > start);
}

/** Walk the chunk for jd in every loaded zone and yield each body alongside
 *  the chunk's validity window (used by callers that build PositionedBody).
 *  Bodies whose chunk hasn't loaded yet are skipped — caller is responsible
 *  for awaiting `load(jd)` first. */
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
	/** Each body's kernel reach: sorted, disjoint spans, JD TDB. */
	bodies: Record<string, [number, number][]>;
}

interface BodyLocation {
	zone: string;
	chunkIdx: number;
	body: ChebyshevBody;
}

/** A body's reach and its zone's, in app (UTC) JD. */
interface Reach {
	zone: string;
	spans: readonly CoverageWindow[];
	zoneSpan: { start: number; end: number };
}

export class ChebyshevStore extends ChunkWindow<FetchedChebyshev, ChebyshevZoneParams> {
	/** Every body the manifest lists, so a query routes without scanning zones
	 *  and a body no loaded chunk holds still has its edges. */
	private readonly reach = new Map<string, Reach>();
	/** Records of the bodies the chunks at the boot date do not hold. */
	private readonly strays = new Map<string, BodyWithWindow>();

	constructor(zoneParams: Map<string, ChebyshevZoneParams>) {
		super(zoneParams);
		for (const [zone, params] of zoneParams) {
			const zoneSpan = { start: tdbToUtc(params.start_jd), end: tdbToUtc(params.end_jd) };
			for (const [id, spans] of Object.entries(params.bodies)) {
				if (this.reach.has(id)) continue;
				const utc = spans.map(([a, b]): CoverageWindow => [tdbToUtc(a), tdbToUtc(b)]);
				this.reach.set(id, { zone, spans: utc, zoneSpan });
			}
		}
	}

	/** The writer leaves out a chunk no body has segments in: asking for it
	 *  would fail, and the boot that waits on it with it. */
	protected isLoadable(params: ChebyshevZoneParams, chunkIdx: number): boolean {
		const start = params.start_jd + chunkIdx * params.chunk_days;
		const end = start + params.chunk_days;
		for (const spans of Object.values(params.bodies)) if (overlaps(spans, start, end)) return true;
		return false;
	}

	protected fetchChunk(
		zone: string,
		params: ChebyshevZoneParams,
		chunkIdx: number,
		priority: RequestPriority
	): Promise<FetchedChebyshev> {
		return fetchChebyshev(zone, params.zoom, chunkIdx, priority);
	}

	has(objectId: string): boolean {
		return this.reach.has(objectId);
	}

	/** The UTC spans the kernels of `objectId` cover, sorted. Undefined when the
	 *  ephemeris does not track it. */
	coverage(objectId: string): readonly CoverageWindow[] | undefined {
		return this.reach.get(objectId)?.spans;
	}

	/** The UTC span of the zone that holds `objectId`: a body edge at it is where
	 *  the whole ephemeris ends, not the body's own kernel. */
	zoneCoverage(objectId: string): { start: number; end: number } | undefined {
		return this.reach.get(objectId)?.zoneSpan;
	}

	/** True while the chunk that covers `jd` for `objectId` is still to come:
	 *  on its way, or waiting for another try. */
	isAwaited(objectId: string, jd: number): boolean {
		const zone = this.reach.get(objectId)?.zone;
		return zone !== undefined && this.awaitedAt(jd, zone);
	}

	private resolve(objectId: string, jd: number): BodyLocation | null {
		const zone = this.reach.get(objectId)?.zone;
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
	 * `load(jd)` to guarantee full coverage). Used by the scene loader
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
	 * Load a record for each body the chunks at `jd` do not hold, from the chunk
	 * of its span nearest `jd`. The scene builds its bodies once, at the boot
	 * date: one born outside its kernels needs a record to be built from, so it
	 * is there when the clock enters them.
	 */
	async loadStrays(jd: number): Promise<void> {
		const tdb = utcToTdb(jd);
		const wanted = new Map<string, [zone: string, chunkIdx: number, ids: string[]]>();
		for (const [zone, params] of this.zoneParams) {
			const here = chunkIndexForJd(params, jd);
			const chunkStart = params.start_jd + here * params.chunk_days;
			const chunkEnd = chunkStart + params.chunk_days;
			for (const [id, spans] of Object.entries(params.bodies)) {
				if (this.reach.get(id)?.zone !== zone || this.strays.has(id)) continue;
				if (spans.length === 0 || overlaps(spans, chunkStart, chunkEnd)) continue;
				const at = nearestInside(spans, tdb);
				const idx = Math.max(
					0,
					Math.min(params.chunks - 1, Math.floor((at - params.start_jd) / params.chunk_days))
				);
				const key = chunkKey(zone, idx);
				const entry = wanted.get(key) ?? [zone, idx, []];
				entry[2].push(id);
				wanted.set(key, entry);
			}
		}
		// Every chunk is waited for: a stray landing after the scene is built is
		// never built.
		const results = await Promise.allSettled(
			[...wanted.values()].map(async ([zone, idx, ids]) => {
				const chunk = await this.fetchChunk(zone, this.zoneParams.get(zone)!, idx, 'high');
				for (const id of ids) {
					const body = chunk.byId.get(id);
					if (body) this.strays.set(id, { zone, body, startJd: chunk.startJd, endJd: chunk.endJd });
				}
			})
		);
		const failed = results.find((r) => r.status === 'rejected');
		if (failed) throw failed.reason;
	}

	/** The records {@link loadStrays} found. */
	strayBodies(): IterableIterator<BodyWithWindow> {
		return this.strays.values();
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
