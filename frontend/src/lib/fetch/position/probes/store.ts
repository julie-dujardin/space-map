/**
 * Per-zone cache of probe chunks: one zone per Hill-sphere-2× region
 * (`probes/interplanetary`, `probes/mercury`, …), each shipping
 * `position/probes/{zone}/{chunkIdx}.bin.gz`.
 *
 * Unlike chebyshev, a probe can appear in multiple zone files at once — a
 * flyby lives in both its planet zone (over the encounter) and interplanetary
 * (the whole flying phase). When zones overlap at a jd, the optional
 * `isPreferred` predicate picks the caller's zone, falling back to metadata
 * order (interplanetary first) when nothing matches.
 *
 * Eager-loads the chunk containing the current JD plus its two neighbors
 * across every zone (same policy as `ChebyshevStore`).
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
import type { PassengerGraft } from '$lib/fetch/position/probes/passenger';

const NEIGHBOR_WINDOW = 1;

/** How many off-clock chunks to keep. A trip refines against two or three dates
 *  and each may pull one chunk per zone, so this holds a whole refinement. */
const WARMED_CHUNKS = 24;

/** Per-zone params from `metadata.position.zones[zone]`. `fit_center_naif_id`
 *  is the body each probe's position is relative to, handed back to callers
 *  to look up world position and GM via systems-global.
 *
 *  `present` lists every chunk index a `.bin.gz` actually exists for, as
 *  sorted non-overlapping ranges — probe zones are sparse (Pluto = a single
 *  New Horizons flyby chunk), so the store consults this before any GET. */
export interface ProbeZoneParams {
	chunks: number;
	chunk_days: number;
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
	/** Identity to build under: its own, except for a craft riding another,
	 *  where `probe` is the carrier's record supplying the ephemeris. */
	id: string;
	probe: Probe;
	startJd: number;
	endJd: number;
}

/** A craft riding another one at some date, as {@link ProbeStore.ridesAt}
 *  reports it. `attached` is false through the handover below — the craft has
 *  let go, but the archive's first fit for it has not started yet. */
export interface Ride {
	passengerId: string;
	carrierId: string;
	carrierName?: string;
	attached: boolean;
}

/** How long past separation a craft keeps reading its carrier's position.
 *  Archives publish fits on the sub-chunk grid, so a solution that begins at
 *  separation is packed from the next slot up — a day out in the planetary
 *  zones, a week in interplanetary. Without this the craft is unplaceable over
 *  its own first hours of flight, which draws as a hole in its trail. The two
 *  drift apart over that stretch (Huygens is ~1000 km off Cassini by the time
 *  its own fits start, against 1.2 million km to Saturn), which is far less
 *  than a pixel wrong at any range the gap is visible from. */
const DETACH_GRACE_DAYS = 7;

interface ProbeLocation {
	zone: string;
	probe: Probe;
	params: ProbeZoneParams;
}

export class ProbeStore {
	/** Whether a record's stamped fit-center body can currently be composed
	 *  against (chebyshev-tracked or live in the scene). Records whose fit
	 *  center fails this are skipped by `resolve`/`probesAt` — their offsets
	 *  are relative to that body, so any fallback anchor misplaces the probe
	 *  by the body's full heliocentric distance. The small-bodies zone
	 *  (Ryugu, 67P, …) resurfaces once its target is promoted; until then the
	 *  probe falls through to its interplanetary fit. Unset = no gating. */
	fitCenterUsable: ((id: string) => boolean) | null = null;

	private readonly zoneParams: Map<string, ProbeZoneParams>;
	/** `zone → chunkIdx → parsed chunk`. */
	private readonly chunks = new Map<string, Map<number, FetchedProbes>>();
	/** Chunks held for dates away from the clock, keyed `zone:chunkIdx` — see
	 *  {@link warmAt}. */
	private readonly warmed = new Map<string, FetchedProbes>();
	/** In-flight `loadChunk` promises keyed by `zone:chunkIdx` — concurrent
	 *  `ensure()` calls don't kick off duplicate fetches. */
	private readonly inflight = new Map<string, Promise<void>>();
	private lastEnsuredJd: number = NaN;
	/** Passenger object id → the ride it is on. See {@link registerCarried}. */
	private readonly carried = new Map<string, PassengerGraft>();
	/** Bumped per stored chunk. The renderer watches it so a paused clock still
	 *  gets a position pass when probe data arrives after the boot pass. */
	private _version = 0;

	get version(): number {
		return this._version;
	}

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
	 * current-jd chunk is resident now, plus a promise that resolves when the
	 * current-jd fetches land — neighbors warm in the background and never
	 * hold the first frame.
	 */
	ensure(jd: number): { ready: boolean; done: Promise<void> } {
		if (jd === this.lastEnsuredJd) {
			// Same jd doesn't mean loaded: the first caller's fetches may still be
			// in flight, and a second awaiter (ensureBody grafting a probe) must
			// not proceed against absent chunks.
			const pending: Promise<void>[] = [];
			for (const [zone, params] of this.zoneParams) {
				const job = this.inflight.get(`${zone}:${chunkIndexForJd(params, jd)}`);
				if (job) pending.push(job);
			}
			return {
				ready: this.allCurrentChunksLoaded(jd),
				done: pending.length > 0 ? Promise.all(pending).then(() => undefined) : Promise.resolve()
			};
		}
		this.lastEnsuredJd = jd;
		const jobs: Promise<void>[] = [];
		const neighbors: [zone: string, idx: number, params: ProbeZoneParams][] = [];
		let ready = true;
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			if (isPresent(params.present, center) && !this.isResident(zone, center)) {
				ready = false;
				const job = this.loadChunk(zone, center, params, 'high');
				if (job) jobs.push(job);
			}
			for (let d = -NEIGHBOR_WINDOW; d <= NEIGHBOR_WINDOW; d++) {
				const idx = center + d;
				if (d === 0 || idx < 0 || idx >= params.chunks) continue;
				if (isPresent(params.present, idx)) neighbors.push([zone, idx, params]);
			}
			// Evict chunks outside the window so scrubbing a long mission timeline
			// doesn't accumulate every visited chunk.
			const zoneMap = this.chunks.get(zone);
			if (zoneMap) {
				for (const idx of zoneMap.keys()) {
					if (idx < center - NEIGHBOR_WINDOW || idx > center + NEIGHBOR_WINDOW) zoneMap.delete(idx);
				}
			}
		}
		const done = jobs.length > 0 ? Promise.all(jobs).then(() => undefined) : Promise.resolve();
		// Neighbors start once the current chunks are in: launched together they
		// share the link, and a boot on a slow one waits for the whole set.
		void done
			.catch(() => {})
			.then(() => {
				for (const [zone, idx, params] of neighbors) {
					this.loadChunk(zone, idx, params, 'low')?.catch(() => {});
				}
			});
		return { ready, done };
	}

	/** Load whatever covers `jd` for the trip planner, off to one side. The
	 *  window above belongs to the clock (one date, drops the rest); a planner
	 *  query years away would evict the clock's own chunks, so these are kept
	 *  apart and capped instead. */
	async warmAt(jd: number): Promise<void> {
		const jobs: Promise<void>[] = [];
		for (const [zone, params] of this.zoneParams) {
			const idx = chunkIndexForJd(params, jd);
			if (idx < 0 || idx >= params.chunks) continue;
			if (!isPresent(params.present, idx)) continue;
			if (this.isResident(zone, idx)) continue;
			const key = `${zone}:${idx}`;
			if (this.warmed.has(key)) continue;
			const existing = this.inflight.get(key);
			if (existing) {
				jobs.push(existing);
				continue;
			}
			const job = this.fetchAndWarm(key, zone, idx, params);
			this.inflight.set(key, job);
			job.finally(() => this.inflight.delete(key));
			jobs.push(job);
		}
		await Promise.all(jobs);
	}

	private async fetchAndWarm(
		key: string,
		zone: string,
		chunkIdx: number,
		params: ProbeZoneParams
	): Promise<void> {
		const chunk = await fetchProbes(zone, chunkIdx, params.float64_coeffs, 'low');
		this.warmed.set(key, chunk);
		// Oldest out: a planner asks about a handful of dates and then stops, and
		// nothing here is on the render path to miss them.
		while (this.warmed.size > WARMED_CHUNKS) {
			const oldest = this.warmed.keys().next().value;
			if (oldest === undefined) break;
			this.warmed.delete(oldest);
		}
	}

	private isResident(zone: string, chunkIdx: number): boolean {
		return this.chunks.get(zone)?.has(chunkIdx) ?? false;
	}

	private fitCenterCovered(probe: Probe): boolean {
		const fc = probe.fitCenter;
		if (!fc || !this.fitCenterUsable) return true;
		return this.fitCenterUsable(fc.id);
	}

	private allCurrentChunksLoaded(jd: number): boolean {
		for (const [zone, params] of this.zoneParams) {
			const center = chunkIndexForJd(params, jd);
			if (!isPresent(params.present, center)) continue;
			if (!this.isResident(zone, center)) return false;
		}
		return true;
	}

	private loadChunk(
		zone: string,
		chunkIdx: number,
		params: ProbeZoneParams,
		priority: RequestPriority
	): Promise<void> | null {
		if (this.isResident(zone, chunkIdx)) return null;
		const key = `${zone}:${chunkIdx}`;
		const existing = this.inflight.get(key);
		if (existing) return existing;
		const job = this.fetchAndStore(zone, chunkIdx, params, priority);
		this.inflight.set(key, job);
		job.finally(() => this.inflight.delete(key));
		return job;
	}

	private async fetchAndStore(
		zone: string,
		chunkIdx: number,
		params: ProbeZoneParams,
		priority: RequestPriority
	): Promise<void> {
		let zoneMap = this.chunks.get(zone);
		if (!zoneMap) {
			zoneMap = new Map();
			this.chunks.set(zone, zoneMap);
		}
		const chunk = await fetchProbes(zone, chunkIdx, params.float64_coeffs, priority);
		zoneMap.set(chunkIdx, chunk);
		this._version++;
	}

	/** Iterate every probe whose chunk for `jd` is loaded, deduped to one entry
	 *  per `probe.id` — `isPreferred`'s zone wins if supplied, else metadata
	 *  order. Sub-chunk coverage isn't checked here; use `resolve` /
	 *  `probeWithCenter` for that. Callers must `await ensure(jd).done` first. */
	*probesAt(
		jd: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): IterableIterator<ProbeWithWindow> {
		const best = new Map<string, ProbeWithWindow>();
		const preferred = new Set<string>();
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx) ?? this.warmed.get(`${zone}:${chunkIdx}`);
			if (!chunk) continue;
			const zonePreferred = isPreferred?.(params.fit_center_naif_id) ?? false;
			for (let i = 0; i < chunk.probes.length; i++) {
				const probe = chunk.probes[i];
				const id = probe.id;
				if (!id) continue;
				if (preferred.has(id)) continue;
				if (!this.fitCenterCovered(probe)) continue;
				const entry: ProbeWithWindow = {
					zone,
					zoneCenterNaifId: params.fit_center_naif_id,
					id,
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
		yield* this.withPassengers(best, jd).values();
	}

	/**
	 * Hand each riding craft its carrier's record under its own identity, so a
	 * craft with no fits of its own still enters the scene. Both stay in: which
	 * of the two is drawn while they share a position is a per-frame call the
	 * renderer makes from {@link ridesAt}, and the pair has to be in the scene
	 * for either to be the one shown after they part.
	 */
	private withPassengers(
		best: Map<string, ProbeWithWindow>,
		jd: number
	): Map<string, ProbeWithWindow> {
		if (this.carried.size === 0) return best;
		const rides: [string, ProbeWithWindow][] = [];
		for (const [id, { carriedFrom: ride }] of this.carried) {
			if (jd < ride.start_jd || jd >= ride.end_jd || best.has(id)) continue;
			const carrier = best.get(ride.object_id);
			if (carrier) rides.push([id, carrier]);
		}
		for (const [id, carrier] of rides) best.set(id, { ...carrier, id });
		return best;
	}

	/**
	 * Note the craft rides another one over `carriedFrom`'s window: {@link probesAt}
	 * emits it off the carrier's record, and every lookup for it inside that
	 * window falls through to the carrier. Registered from the focused probe's
	 * `coverage.position_from`; unknown craft are simply never carried.
	 */
	registerCarried(passenger: PassengerGraft): void {
		this.carried.set(passenger.id, passenger);
	}

	/**
	 * The craft whose records answer for `objectId` at `jd` once its own have come
	 * up empty, or null when it flies under its own power. A passenger is bolted
	 * to its carrier, so every question about it — where it is, which system it is
	 * in, whether its fit is heliocentric — has the carrier's answer. Callers try
	 * their own lookup first: a record of its own wins, since a lander's descent
	 * kernel starts at separation.
	 */
	private carrierAt(objectId: string, jd: number): string | null {
		if (this.carried.size === 0) return null;
		const ride = this.carried.get(objectId)?.carriedFrom;
		if (!ride || jd < ride.start_jd || jd >= ride.end_jd + DETACH_GRACE_DAYS) return null;
		return ride.object_id;
	}

	/**
	 * The rides live at `jd`, passenger and carrier both named. The renderer
	 * draws one marker for the pair — they are far closer together than a pixel
	 * — and captions it with the carrier while `attached`.
	 *
	 * A ride outlives separation for as long as the archive has nothing of the
	 * craft's own, where the carrier's position beats no position at all. It
	 * ends the moment the craft's own record answers.
	 */
	ridesAt(jd: number): Ride[] {
		const out: Ride[] = [];
		for (const [id, passenger] of this.carried) {
			const ride = passenger.carriedFrom;
			if (jd < ride.start_jd || jd >= ride.end_jd + DETACH_GRACE_DAYS) continue;
			const attached = jd < ride.end_jd;
			if (!attached && this.resolveOwn(id, jd)) continue;
			out.push({
				passengerId: id,
				carrierId: ride.object_id,
				carrierName: passenger.carrierName,
				attached
			});
		}
		return out;
	}

	private resolve(
		objectId: string,
		jd: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): ProbeLocation | null {
		const own = this.resolveOwn(objectId, jd, isPreferred);
		if (own) return own;
		const carrier = this.carrierAt(objectId, jd);
		return carrier ? this.resolveOwn(carrier, jd, isPreferred) : null;
	}

	/** Iterate zones in metadata order, returning the first record for
	 *  `objectId` whose sub-chunks cover `jd`. Falls through zones with no
	 *  covering record — handles cross-zone transitions (cruise → captured
	 *  orbit) so the renderer follows the live zone without a hidden frame. A
	 *  covering record in a preferred zone (`isPreferred`) always wins, e.g. a
	 *  Mars-flyby probe gets its Mars-relative fit when zoomed into Mars. */
	private resolveOwn(
		objectId: string,
		jd: number,
		isPreferred?: (fitCenterNaif: number) => boolean
	): ProbeLocation | null {
		const et = jdToEt(jd);
		let firstMatch: ProbeLocation | null = null;
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx) ?? this.warmed.get(`${zone}:${chunkIdx}`);
			if (!chunk) continue;
			for (const i of rowsFor(chunk, objectId)) {
				const probe = chunk.probes[i];
				if (!this.fitCenterCovered(probe)) break;
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

	/** Stamped fit-center id of the record that would win for `objectId` at
	 *  `jd` were its body placeable, or null (no record / no stamp). Ungated
	 *  on purpose: it tells the scene which body to promote so the precise
	 *  fit can take over (Ryugu when Hayabusa2 is focused). */
	stampedFitCenterAt(objectId: string, jd: number): string | null {
		const own = this.stampedFitCenterAtOwn(objectId, jd);
		if (own !== null) return own;
		const carrier = this.carrierAt(objectId, jd);
		return carrier ? this.stampedFitCenterAtOwn(carrier, jd) : null;
	}

	private stampedFitCenterAtOwn(objectId: string, jd: number): string | null {
		const et = jdToEt(jd);
		for (const [zone, params] of this.zoneParams) {
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx) ?? this.warmed.get(`${zone}:${chunkIdx}`);
			if (!chunk) continue;
			for (const i of rowsFor(chunk, objectId)) {
				const probe = chunk.probes[i];
				if (findSubChunkIndex(probe, et) < 0) break;
				return probe.fitCenter?.id ?? null;
			}
		}
		return null;
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
	 * Planetary-system barycenter NAIF the probe is inside, or `null` for
	 * heliocentric cruise / unknown. Interplanetary chunk's `systemIntervals`
	 * wins first; a miss means pure cruise. Falls back to walking planet zones
	 * for probes only present there, deriving the barycenter as
	 * `floor(fit_center_naif_id / 100)` (199→1, 499→4, …).
	 */
	containingSystemAt(probeId: string, jd: number): number | null {
		const own = this.containingSystemAtOwn(probeId, jd);
		if (own !== null) return own;
		const carrier = this.carrierAt(probeId, jd);
		return carrier ? this.containingSystemAtOwn(carrier, jd) : null;
	}

	private containingSystemAtOwn(probeId: string, jd: number): number | null {
		const et = jdToEt(jd);
		const interParams = this.zoneParams.get(INTERPLANETARY_ZONE);
		if (interParams) {
			const chunkIdx = chunkIndexForJd(interParams, jd);
			const chunk = this.chunks.get(INTERPLANETARY_ZONE)?.get(chunkIdx);
			if (chunk) {
				for (const i of rowsFor(chunk, probeId)) {
					const probe = chunk.probes[i];
					for (const iv of probe.systemIntervals) {
						if (et >= iv.startEt && et < iv.endEt) return iv.systemNaifId;
					}
					return null;
				}
			}
		}
		for (const [zone, params] of this.zoneParams) {
			// Sun-centered zones (small-bodies) have no containing planetary system.
			if (zone === INTERPLANETARY_ZONE || params.fit_center_naif_id === 10) continue;
			const chunkIdx = chunkIndexForJd(params, jd);
			const chunk = this.chunks.get(zone)?.get(chunkIdx);
			if (!chunk) continue;
			for (const i of rowsFor(chunk, probeId)) {
				return Math.floor(params.fit_center_naif_id / 100);
			}
		}
		return null;
	}

	/**
	 * True when the probe has a heliocentric (interplanetary) fit covering `jd` —
	 * flyby and cruise probes do (Sun-relative fit even inside a planet's Hill
	 * sphere); a captured orbiter, emitted only to its planet zone, does not.
	 */
	hasHeliocentricFit(objectId: string, jd: number): boolean {
		if (this.hasHeliocentricFitOwn(objectId, jd)) return true;
		const carrier = this.carrierAt(objectId, jd);
		return carrier !== null && this.hasHeliocentricFitOwn(carrier, jd);
	}

	private hasHeliocentricFitOwn(objectId: string, jd: number): boolean {
		const params = this.zoneParams.get(INTERPLANETARY_ZONE);
		if (!params) return false;
		const chunkIdx = chunkIndexForJd(params, jd);
		const chunk = this.chunks.get(INTERPLANETARY_ZONE)?.get(chunkIdx);
		if (!chunk) return false;
		const et = jdToEt(jd);
		for (const i of rowsFor(chunk, objectId)) {
			if (findSubChunkIndex(chunk.probes[i], et) >= 0) return true;
		}
		return false;
	}
}

/** Heliocentric catch-all zone. Its records carry the `systemIntervals`
 *  annotation that drives flyby focus + visibility. */
const INTERPLANETARY_ZONE = 'probes/interplanetary';

const NO_ROWS: readonly number[] = [];
/** Per-chunk id → rows index, built on first use. A probe can hold several
 *  records in one chunk, so callers walk the rows in file order. */
const rowIndex = new WeakMap<FetchedProbes, Map<string, number[]>>();
function rowsFor(chunk: FetchedProbes, id: string): readonly number[] {
	let index = rowIndex.get(chunk);
	if (!index) {
		index = new Map();
		for (let i = 0; i < chunk.ids.length; i++) {
			const rows = index.get(chunk.ids[i]);
			if (rows) rows.push(i);
			else index.set(chunk.ids[i], [i]);
		}
		rowIndex.set(chunk, index);
	}
	return index.get(id) ?? NO_ROWS;
}
