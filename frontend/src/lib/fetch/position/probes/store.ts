/**
 * Per-zone cache of probe chunks. One zone per Hill-sphere-2× region
 * (`probes/interplanetary`, `probes/mercury`, …, `probes/pluto`); each ships
 * `position/probes/{zone}/{chunkIdx}.bin.gz` with no zoom segment.
 *
 * Unlike chebyshev, a probe can appear in *multiple* zone files at different
 * times — cruise samples land in `probes/interplanetary`, captured-orbit
 * samples land in `probes/{planet}`. The same `probe_id` therefore re-appears
 * across zones with disjoint sub-chunk coverage; the store picks the right
 * zone+chunk for the current jd by ET-window match.
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

const DAYS_PER_YEAR = 365.25;
const NEIGHBOR_WINDOW = 1;

/** Per-zone params lifted from `metadata.position.zones[zone]` (flat, no
 *  `zooms` wrapper). `fit_center_naif_id` is the body each probe's position
 *  is relative to (10=Sun for interplanetary, 199=Mercury, …); the store
 *  hands it back to callers so they can look up the body's world position
 *  and GM via the systems-global file. */
export interface ProbeZoneParams {
	chunks: number;
	chunk_years: number;
	start_jd: number;
	end_jd: number;
	float64_coeffs: boolean;
	fit_center_naif_id: number;
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

function chunkIndexForJd(zone: ProbeZoneParams, jd: number): number {
	const dt = jd - zone.start_jd;
	const idx = Math.floor(dt / (zone.chunk_years * DAYS_PER_YEAR));
	return Math.max(0, Math.min(zone.chunks - 1, idx));
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
	/** Per-zone set of chunk indices known to have no file on the export
	 *  (sparse-zone gap). Marked once on 404/403, so subsequent `ensure()`
	 *  calls don't re-issue fetches and downstream code treats "absent" the
	 *  same as "loaded but empty". */
	private readonly absent = new Map<string, Set<number>>();
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
			if (!this.isResident(zone, center)) ready = false;
			for (let d = -NEIGHBOR_WINDOW; d <= NEIGHBOR_WINDOW; d++) {
				const idx = center + d;
				if (idx < 0 || idx >= params.chunks) continue;
				const job = this.loadChunk(zone, idx, params);
				if (job) jobs.push(job);
			}
		}
		return {
			ready,
			done: jobs.length > 0 ? Promise.all(jobs).then(() => undefined) : Promise.resolve()
		};
	}

	/** True when `chunkIdx` for `zone` is either loaded or known absent —
	 *  both states mean "no further fetch needed". */
	private isResident(zone: string, chunkIdx: number): boolean {
		return (
			(this.chunks.get(zone)?.has(chunkIdx) ?? false) ||
			(this.absent.get(zone)?.has(chunkIdx) ?? false)
		);
	}

	private allCurrentChunksLoaded(jd: number): boolean {
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
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
		if (chunk === null) {
			let absentSet = this.absent.get(zone);
			if (!absentSet) {
				absentSet = new Set();
				this.absent.set(zone, absentSet);
			}
			absentSet.add(chunkIdx);
			return;
		}
		zoneMap.set(chunkIdx, chunk);
	}

	/**
	 * Iterate every probe whose chunk for `jd` is loaded, across every zone.
	 * The same `probe_id` can appear in multiple zones (cruise + captured
	 * orbit) at different jd windows — sub-chunk presence is the gate, not
	 * zone membership. Callers must `await ensure(jd).done` first.
	 */
	*probesAt(jd: number): IterableIterator<ProbeWithWindow> {
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			for (const probe of chunk.probes) {
				yield {
					zone,
					zoneCenterNaifId: params.fit_center_naif_id,
					probe,
					startJd: chunk.startJd,
					endJd: chunk.endJd
				};
			}
		}
	}

	/** Iterate zones in metadata order; for each, find every record matching
	 *  `objectId` in the chunk for `jd` (the writer may emit >1 record per probe
	 *  per chunk when an interval splits inside the chunk window) and return the
	 *  first one whose sub-chunks actually cover `jd`. Falls through to the next
	 *  zone if the records exist but none cover `jd` — handles cross-zone
	 *  transitions (cruise → captured orbit at a flyby/capture boundary): the
	 *  interplanetary chunk lists the probe up to the boundary, the planet
	 *  chunk picks up from there, and the renderer follows the live one without
	 *  a frame where the probe is hidden. */
	private resolve(objectId: string, jd: number): ProbeLocation | null {
		const et = jdToEt(jd);
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			for (let i = 0; i < chunk.probes.length; i++) {
				if (chunk.ids[i] !== objectId) continue;
				const probe = chunk.probes[i];
				if (findSubChunkIndex(probe, et) < 0) continue;
				return { zone, probe, params };
			}
		}
		return null;
	}

	/** Parsed probe record for `objectId` at `jd`, across every loaded zone.
	 *  Returns null if no zone's chunk for jd lists this probe. */
	probe(objectId: string, jd: number): Probe | null {
		return this.resolve(objectId, jd)?.probe ?? null;
	}

	/** Parsed probe record + zone fit-center NAIF ID at `jd`. Use this when the
	 *  caller needs to follow cross-zone transitions (e.g. cruise → captured
	 *  orbit changes the fit center from Sun to a planet, and Kepler-pure mean
	 *  motion `sqrt(mu/a³)` is mu-sensitive). */
	probeWithCenter(objectId: string, jd: number): { probe: Probe; fitCenterNaifId: number } | null {
		const loc = this.resolve(objectId, jd);
		if (!loc) return null;
		return { probe: loc.probe, fitCenterNaifId: loc.params.fit_center_naif_id };
	}

	/** Parent-relative probe position in km at `jd`, with `mu` (km³/s²) of the
	 *  zone's fit center supplied by the caller. Returns null if the probe
	 *  isn't loaded or jd is outside any sub-chunk's window. */
	positionKm(objectId: string, jd: number, muKm3S2: number): [number, number, number] | null {
		const loc = this.resolve(objectId, jd);
		if (!loc) return null;
		return probePositionKm(loc.probe, jd, muKm3S2);
	}

	/** Parent-relative probe position in Three.js scene units. */
	positionScene(objectId: string, jd: number, muKm3S2: number): [number, number, number] | null {
		const loc = this.resolve(objectId, jd);
		if (!loc) return null;
		return probePositionScene(loc.probe, jd, muKm3S2);
	}
}
