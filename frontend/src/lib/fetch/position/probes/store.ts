/**
 * Per-zone cache of probe chunks. One zone per Hill-sphere-2× region
 * (`probes/interplanetary`, `probes/mercury`, …, `probes/pluto`); each ships
 * `position/probes/{zone}/{chunkIdx}.bin.gz` with no zoom segment.
 *
 * Unlike chebyshev, a probe can appear in *multiple* zone files: cruise
 * samples land in `probes/interplanetary`, captured-orbit samples land in
 * `probes/{planet}`, and a flyby probe lives in BOTH at once (the planet
 * zone over the encounter, interplanetary across the whole flying phase —
 * see data/probes/trace.py). When zones overlap at a jd, the resolver picks
 * the zone the caller asks for via the optional `isPreferred` predicate
 * (typically "is this zone's fit center inside the user's focused system?")
 * and falls through to the metadata-iteration order (interplanetary first →
 * heliocentric fit for the solar view) when nothing matches.
 *
 * Eager-loads the chunk containing the current JD plus its two neighbors
 * across every zone (same policy as `ChebyshevStore`). Sub-chunks within a
 * chunk are time-windowed so callers can dispatch position(jd) by binary
 * search through the parsed `Probe` record.
 */

import { fetchProbes, type FetchedProbes } from '$lib/fetch/position/probes/fetch';
import {
	findSubChunkIndex,
	jdToEt,
	probePositionKm,
	probePositionScene
} from '$lib/fetch/position/probes/propagate';
import type { Probe } from '$lib/fetch/position/probes/parse';
import { chunkIndexForJd } from '$lib/fetch/metadata';

const NEIGHBOR_WINDOW = 1;

/** Per-zone params lifted from `metadata.position.zones[zone]` (flat, no
 *  `zooms` wrapper). `fit_center_naif_id` is the body each probe's position
 *  is relative to (10=Sun for interplanetary, 199=Mercury, …); the store
 *  hands it back to callers so they can look up the body's world position
 *  and GM via the systems-global file.
 *
 *  `present` lists every chunk index a `.bin.gz` actually exists for, as
 *  inclusive-inclusive ranges (sorted, non-overlapping). Probe zones are
 *  sparse — `chunks` is the full theoretical span across `[start_jd, end_jd]`,
 *  but most slots have no file (Pluto = single New Horizons flyby chunk,
 *  Uranus/Neptune = a single Voyager 2 flyby pair, …). The store consults
 *  `present` before issuing any GET so absent chunks cost zero round-trips. */
export interface ProbeZoneParams {
	chunks: number;
	chunk_years: number;
	start_jd: number;
	end_jd: number;
	float64_coeffs: boolean;
	fit_center_naif_id: number;
	present: [number, number][];
}

/** True iff `idx` falls inside any range in `present`. Ranges are sorted
 *  ascending and non-overlapping; once `idx < range.start` we can return early. */
function isPresent(present: [number, number][], idx: number): boolean {
	for (const [s, e] of present) {
		if (idx < s) return false;
		if (idx <= e) return true;
	}
	return false;
}

/** Yielded by `probesAt` so the scene loader can build PositionedBody for
 *  each probe alive at jd. The chunk's JD validity bounds let downstream
 *  visibility code hide probes outside their window without re-querying. */
export interface ProbeWithWindow {
	zone: string;
	zoneCenterNaifId: number;
	probe: Probe;
	startJd: number;
	endJd: number;
}

interface ProbeLocation {
	zone: string;
	probe: Probe;
	params: ProbeZoneParams;
}

export class ProbeStore {
	private readonly zoneParams: Map<string, ProbeZoneParams>;
	/** `zone → chunkIdx → parsed chunk`. */
	private readonly chunks = new Map<string, Map<number, FetchedProbes>>();
	/** In-flight `loadChunk` promises keyed by `zone:chunkIdx` — concurrent
	 *  `ensure()` calls don't kick off duplicate fetches. */
	private readonly inflight = new Map<string, Promise<void>>();
	private lastEnsuredJd: number = NaN;

	constructor(zoneParams: Map<string, ProbeZoneParams>) {
		this.zoneParams = zoneParams;
	}

	zones(): string[] {
		return Array.from(this.zoneParams.keys());
	}

	zoneCenter(zone: string): number | undefined {
		return this.zoneParams.get(zone)?.fit_center_naif_id;
	}

	/**
	 * Warm the chunks covering `jd` (and ±NEIGHBOR_WINDOW neighbors) for every
	 * probe zone. Idempotent, safe to call every frame. Returns whether every
	 * current-jd chunk is resident now, plus a promise that resolves when any
	 * in-flight fetches land.
	 */
	ensure(jd: number): { ready: boolean; done: Promise<void> } {
		if (jd === this.lastEnsuredJd) {
			return { ready: this.allCurrentChunksLoaded(jd), done: Promise.resolve() };
		}
		this.lastEnsuredJd = jd;
		const jobs: Promise<void>[] = [];
		let ready = true;
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			if (isPresent(params.present, center) && !this.isResident(zone, center)) {
				ready = false;
			}
			for (let d = -NEIGHBOR_WINDOW; d <= NEIGHBOR_WINDOW; d++) {
				const idx = center + d;
				if (idx < 0 || idx >= params.chunks) continue;
				if (!isPresent(params.present, idx)) continue;
				const job = this.loadChunk(zone, idx, params);
				if (job) jobs.push(job);
			}
		}
		return {
			ready,
			done: jobs.length > 0 ? Promise.all(jobs).then(() => undefined) : Promise.resolve()
		};
	}

	private isResident(zone: string, chunkIdx: number): boolean {
		return this.chunks.get(zone)?.has(chunkIdx) ?? false;
	}

	private allCurrentChunksLoaded(jd: number): boolean {
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			if (!isPresent(params.present, center)) continue;
			if (!this.isResident(zone, center)) return false;
		}
		return true;
	}

	private loadChunk(zone: string, chunkIdx: number, params: ProbeZoneParams): Promise<void> | null {
		if (this.isResident(zone, chunkIdx)) return null;
		const key = `${zone}:${chunkIdx}`;
		const existing = this.inflight.get(key);
		if (existing) return existing;
		const job = this.fetchAndStore(zone, chunkIdx, params);
		this.inflight.set(key, job);
		job.finally(() => this.inflight.delete(key));
		return job;
	}

	private async fetchAndStore(
		zone: string,
		chunkIdx: number,
		params: ProbeZoneParams
	): Promise<void> {
		let zoneMap = this.chunks.get(zone);
		if (!zoneMap) {
			zoneMap = new Map();
			this.chunks.set(zone, zoneMap);
		}
		const chunk = await fetchProbes(zone, chunkIdx, params.float64_coeffs);
		zoneMap.set(chunkIdx, chunk);
	}

	/**
	 * Iterate every probe whose chunk for `jd` is loaded, deduped to one entry
	 * per `probe.id`. When `isPreferred` is supplied, the zone whose fit center
	 * passes the predicate wins; otherwise the first zone in metadata order
	 * (interplanetary first) wins. Sub-chunk coverage is NOT checked here —
	 * callers needing coverage gate via `resolve` / `probeWithCenter`. Callers
	 * must `await ensure(jd).done` first.
	 */
	*probesAt(
		jd: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): IterableIterator<ProbeWithWindow> {
		const best = new Map<string, ProbeWithWindow>();
		const preferred = new Set<string>();
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			const zonePreferred = isPreferred?.(params.fit_center_naif_id) ?? false;
			for (let i = 0; i < chunk.probes.length; i++) {
				const probe = chunk.probes[i];
				const id = probe.id;
				if (!id) continue;
				if (preferred.has(id)) continue;
				const entry: ProbeWithWindow = {
					zone,
					zoneCenterNaifId: params.fit_center_naif_id,
					probe,
					startJd: chunk.startJd,
					endJd: chunk.endJd
				};
				if (zonePreferred) {
					best.set(id, entry);
					preferred.add(id);
				} else if (!best.has(id)) {
					best.set(id, entry);
				}
			}
		}
		yield* best.values();
	}

	/** Iterate zones in metadata order; for each, find every record matching
	 *  `objectId` in the chunk for `jd` (the writer may emit >1 record per probe
	 *  per chunk when an interval splits inside the chunk window) and return the
	 *  first one whose sub-chunks actually cover `jd`. Falls through to the next
	 *  zone if the records exist but none cover `jd` — handles cross-zone
	 *  transitions (cruise → captured orbit at a flyby/capture boundary): the
	 *  interplanetary chunk lists the probe up to the boundary, the planet
	 *  chunk picks up from there, and the renderer follows the live one without
	 *  a frame where the probe is hidden.
	 *
	 *  When `isPreferred` is supplied, a covering record in a preferred zone
	 *  beats a covering record in any other zone — so a Mars-flyby probe gets
	 *  its Mars-relative fit (and parentId=Mars) when the user is zoomed into
	 *  Mars, but its heliocentric fit otherwise. */
	private resolve(
		objectId: string,
		jd: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): ProbeLocation | null {
		const et = jdToEt(jd);
		let firstMatch: ProbeLocation | null = null;
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			for (let i = 0; i < chunk.probes.length; i++) {
				if (chunk.ids[i] !== objectId) continue;
				const probe = chunk.probes[i];
				const hasFlying = findSubChunkIndex(probe, et) >= 0;
				const landed = probe.landed;
				const hasLanded = landed !== undefined && et >= landed.startEt && et < landed.endEt;
				// Either path matches — the renderer dispatches between flying
				// sub-chunks (kepler/chebyshev) and the trailing landed record.
				if (!hasFlying && !hasLanded) continue;
				const loc: ProbeLocation = { zone, probe, params };
				if (isPreferred?.(params.fit_center_naif_id)) return loc;
				firstMatch ??= loc;
				break;
			}
		}
		return firstMatch;
	}

	/** Parsed probe record for `objectId` at `jd`, across every loaded zone.
	 *  Returns null if no zone's chunk for jd lists this probe. */
	probe(
		objectId: string,
		jd: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): Probe | null {
		return this.resolve(objectId, jd, isPreferred)?.probe ?? null;
	}

	/** Parsed probe record + zone fit-center NAIF ID at `jd`. Use this when the
	 *  caller needs to follow cross-zone transitions (e.g. cruise → captured
	 *  orbit changes the fit center from Sun to a planet, and Kepler-pure mean
	 *  motion `sqrt(mu/a³)` is mu-sensitive). */
	probeWithCenter(
		objectId: string,
		jd: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): { probe: Probe; fitCenterNaifId: number } | null {
		const loc = this.resolve(objectId, jd, isPreferred);
		if (!loc) return null;
		return { probe: loc.probe, fitCenterNaifId: loc.params.fit_center_naif_id };
	}

	/** Parent-relative probe position in km at `jd`, with `mu` (km³/s²) of the
	 *  zone's fit center supplied by the caller. Returns null if the probe
	 *  isn't loaded or jd is outside any sub-chunk's window. */
	positionKm(
		objectId: string,
		jd: number,
		muKm3S2: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): [number, number, number] | null {
		const loc = this.resolve(objectId, jd, isPreferred);
		if (!loc) return null;
		return probePositionKm(loc.probe, jd, muKm3S2);
	}

	/** Parent-relative probe position in Three.js scene units. */
	positionScene(
		objectId: string,
		jd: number,
		muKm3S2: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): [number, number, number] | null {
		const loc = this.resolve(objectId, jd, isPreferred);
		if (!loc) return null;
		return probePositionScene(loc.probe, jd, muKm3S2);
	}

	/**
	 * Planetary-system barycenter NAIF the probe is currently inside, or `null`
	 * for heliocentric cruise / unknown. Lets focus + visibility route a flyby
	 * probe (Psyche through Mars, Voyager through Jupiter) to the right system
	 * synchronously, without waiting for the planet zone's chunk to land.
	 *
	 * Resolution order:
	 *   1. Interplanetary chunk → consult `systemIntervals` (writer-stamped:
	 *      "in Mars system from t0 to t1"). Half-open: `startEt ≤ et < endEt`.
	 *      A hit returns the system NAIF; a miss means the probe is in
	 *      interplanetary but in pure cruise → `null`.
	 *   2. Fallback (probe is purely captured, e.g. MEX, MAVEN — not in
	 *      interplanetary): walk planet zones; the zone identity *is* the
	 *      system. Returns `barycenter_naif_id`, derived from the zone's
	 *      `fit_center_naif_id` via integer-divide by 100 (199→1, 499→4, …).
	 *
	 * Returns `null` if no chunk has the probe at jd (mid-async-load, or the
	 * probe simply doesn't exist at that jd).
	 */
	containingSystemAt(probeId: string, jd: number): number | null {
		const et = jdToEt(jd);
		const interParams = this.zoneParams.get(INTERPLANETARY_ZONE);
		if (interParams) {
			const chunkIdx = chunkIndexForJd(interParams, jd);
			const chunk = this.chunks.get(INTERPLANETARY_ZONE)?.get(chunkIdx);
			if (chunk) {
				for (let i = 0; i < chunk.ids.length; i++) {
					if (chunk.ids[i] !== probeId) continue;
					const probe = chunk.probes[i];
					for (const iv of probe.systemIntervals) {
						if (et >= iv.startEt && et < iv.endEt) return iv.systemNaifId;
					}
					return null;
				}
			}
		}
		for (const [zone, params] of this.zoneParams) {
			if (zone === INTERPLANETARY_ZONE) continue;
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			for (let i = 0; i < chunk.ids.length; i++) {
				if (chunk.ids[i] !== probeId) continue;
				return Math.floor(params.fit_center_naif_id / 100);
			}
		}
		return null;
	}
}

/** Zone key for the heliocentric catch-all probe zone. The frontend treats it
 *  specially: it's always loaded (ensure() warms every zone), and its records
 *  carry the writer-stamped `systemIntervals` annotation that drives flyby
 *  focus + visibility without needing planet-zone chunks. */
const INTERPLANETARY_ZONE = 'probes/interplanetary';
