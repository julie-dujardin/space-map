import { ObjectType, ZONE_A_RANGE, type BodyData, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/elements/chunk';
import { OrbitalSource } from '$lib/fetch/elements/constants';
import { AU_KM, AU_SCALE } from '../math/units';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/orbit/position';
import { buildSatrec, sgp4PositionScene } from '$lib/math/orbit/sgp4';
import { fetchObjectDetail } from '$lib/fetch/objects/object-data';
import { loadNutPrecAngles } from '$lib/fetch/nut-prec-angles';
import { fetchMetadata, isTimeSegmented, snapshotDate } from '$lib/fetch/metadata';
import { dateToJD } from '$lib/format/date';
import { ChebyshevStore } from '$lib/fetch/chebyshev/store';
import { TrailBuffer } from '$lib/fetch/chebyshev/trail-buffer';
import { populateTrailBuffer } from '$lib/fetch/elements/chunk';

/*
 * Visibility options:
 * CLOSE: too close to show everything, revert to point cloud.
 * FULL: show halos and trails.
 * CAPPED: In range for FULL but rejected by the crowding cap — point cloud by default, minimized halo when hideCappedMoonLabels=true.
 * FAR: point cloud.
 * HIDE: hide entirely.
 */
export enum VISIBILITY {
	CLOSE = 1,
	FULL = 2,
	CAPPED = 3,
	FAR = 4,
	HIDE = 5
}
/*
 * Distance ratio thresholds for visibility levels.
 * Ratio is (camera distance to focused body / moon semi-major axis), both in AU.
 * These were tuned for a 27" 1440p monitor; FULL and FAR are scaled at runtime by screenScaleFactor.
 */
/** Viewport height (CSS px) the distance-ratio thresholds were tuned for. */
const REFERENCE_VIEWPORT_HEIGHT = 1503;

export const PLANETARY_DISTANCE_RATIO_THRESHOLDS = {
	[VISIBILITY.CLOSE]: 0.3,
	[VISIBILITY.FULL]: 20,
	[VISIBILITY.FAR]: 100,
	[VISIBILITY.HIDE]: Infinity
};
export const SYSTEM_DISTANCE_RATIO_THRESHOLDS = {
	[VISIBILITY.CLOSE]: 0.01,
	[VISIBILITY.FULL]: 20,
	[VISIBILITY.FAR]: 100,
	[VISIBILITY.HIDE]: Infinity
};

/** Multiplier applied to the FULL threshold for the currently focused body. */
const FOCUSED_FULL_MULTIPLIER_MOON = 5;
const FOCUSED_FULL_MULTIPLIER_SPACECRAFT = 50; // TODO: check with spacecraft that orbit farther than GEO

/** Max number of moons shown at FULL visibility simultaneously. Excess (outermost) are demoted to FAR. */
export const MAX_FULL_MOONS = 20;

/** Below this distance, hide other systems (halos, orbits, spacecraft). */
export const ZOOM_THRESHOLD_AU = 0.05;

/** Shared ratio→VISIBILITY mapping used by both moon and planet/spacecraft visibility. */
function computeVisibilityFromRatio(
	ratio: number,
	thresholds: typeof PLANETARY_DISTANCE_RATIO_THRESHOLDS,
	focusedMultiplier: number,
	isFocused: boolean
): VISIBILITY {
	if (ratio <= thresholds[VISIBILITY.CLOSE]) return VISIBILITY.CLOSE;
	if (ratio <= thresholds[VISIBILITY.FULL] * (isFocused ? focusedMultiplier : 1))
		return VISIBILITY.FULL;
	if (ratio <= thresholds[VISIBILITY.FAR]) return VISIBILITY.FAR;
	return VISIBILITY.HIDE;
}

/** Map a GlobalObjectData.type string (e.g. "asteroid_main_belt") to the ObjectType enum. */
function parseObjectType(typeStr: string): ObjectType {
	const key = typeStr.toUpperCase() as keyof typeof ObjectType;
	return ObjectType[key] ?? ObjectType.UNDOCUMENTED;
}

/**
 * Map a global JSON `orbit.source` string (the lowercase `OrbitalSource` enum
 * value) back to the numeric ordinal — placeholder bodies created before their
 * chunk lands have no binary header to pull from, so we parse the string.
 * Returns `UNKNOWN` if the server sent a value the frontend doesn't know.
 */
const ORBIT_SOURCE_BY_NAME: Record<string, OrbitalSource> = {
	horizons: OrbitalSource.HORIZONS,
	sbdb: OrbitalSource.SBDB,
	celestrak: OrbitalSource.CELESTRAK,
	spice: OrbitalSource.SPICE
};
function parseOrbitalSource(name: string | undefined): OrbitalSource {
	if (!name) return OrbitalSource.UNKNOWN;
	return ORBIT_SOURCE_BY_NAME[name] ?? OrbitalSource.UNKNOWN;
}

/**
 * Per-body texture attribution recorded when its system metadata loads.
 * `systemId` is the barycenter ID the body belongs to, used by the bar to
 * show imagery credits only for the focused system while the popover shows
 * every loaded texture regardless of focus.
 */
export interface TextureCredit {
	bodyId: string;
	systemId: string;
	source: string;
	organisation: string;
	type: string;
	attribution?: string;
	description?: string;
}

/**
 * Create a placeholder PositionedBody from the __global__ object file along
 * with the SBDB-class zone id (e.g. `"MBA"`) for routing — null when the
 * object has no SBDB record, in which case the caller falls back to
 * `parentId`-based routing (spacecraft/debris) or `bodiesById` (majors).
 *
 * Returns null if the object doesn't exist or has no orbit data.
 */
async function createPlaceholderBody(
	targetId: string,
	date: Date,
	loader: ChunkLoader
): Promise<{ body: PositionedBody; zone: string | null } | null> {
	let detail: Awaited<ReturnType<typeof fetchObjectDetail>>;
	try {
		detail = await fetchObjectDetail(targetId);
	} catch {
		console.warn(`Failed to fetch global data for ${targetId}`);
		return null;
	}
	const global = detail.global;
	if (!global?.orbit) return null;

	const orbit = global.orbit;
	const isPlanetScale = orbit.scale === 'planet';
	const isParabolic = orbit.q != null;

	const noradCatId = global.cross_refs?.norad_cat_id;
	const hasSGP4Fields =
		orbit.bstar != null &&
		orbit.mean_motion_dot != null &&
		orbit.mean_motion_ddot != null &&
		orbit.n != null &&
		noradCatId != null;
	const satrec =
		isPlanetScale && hasSGP4Fields
			? (buildSatrec(
					{
						noradCatId,
						epochJd: orbit.epoch_jd,
						meanMotion: orbit.n!,
						eccentricity: orbit.e,
						inclination: orbit.i,
						raOfAscNode: orbit.om,
						argOfPericenter: orbit.w,
						meanAnomaly: orbit.ma ?? 0,
						bstar: orbit.bstar!,
						meanMotionDot: orbit.mean_motion_dot!,
						meanMotionDdot: orbit.mean_motion_ddot!,
						elementSetNo: orbit.element_set_no ?? 0,
						revAtEpoch: orbit.rev_at_epoch ?? 0
					},
					global.name ?? undefined
				) ?? undefined)
			: undefined;

	// SGP4 placeholders (URL-navigated Earth sats arriving before the chunk)
	// need a tight validity window so the per-frame propagation gate hides
	// them when the sim time wanders far from epoch — the chunk's real window
	// will overwrite this once it loads. Keplerian/parabolic orbits have no
	// hard cutoff, so leave them unbounded.
	const SGP4_VALIDITY_SLACK_DAYS = 14;
	const validityStart = satrec ? orbit.epoch_jd - SGP4_VALIDITY_SLACK_DAYS : -Infinity;
	const validityEnd = satrec ? orbit.epoch_jd + SGP4_VALIDITY_SLACK_DAYS : Infinity;

	const data: BodyData = {
		id: targetId,
		// Prefer the localized (Wikidata-resolved) long form so the 3D label matches
		// what the element chunk would produce via resolve_name; global.name is the
		// raw short form (e.g. CelesTrak "IRIDIUM 33 DEB") and only a last resort.
		name:
			detail.localized?.name ??
			global.name ??
			global.sbdb_primary_designation ??
			global.provisional_designation ??
			null,
		objectType: parseObjectType(global.type),
		parentId: `naif-${orbit.parent_naif_id}`,
		radiusKm: global.sbdb?.diameter ? global.sbdb.diameter / 2 : NaN,
		objectFileFlag: detail.localized ? 1 : 0,
		a: isPlanetScale ? (orbit.a ?? 0) / AU_KM : (orbit.a ?? 0),
		e: orbit.e,
		i: orbit.i,
		om: orbit.om,
		w: orbit.w,
		ma: orbit.ma ?? 0,
		n: isPlanetScale ? (orbit.n ?? 0) * 360 : (orbit.n ?? 0),
		epoch: orbit.epoch_jd,
		// Planet-scale means CelesTrak TLE data, which uses Earth-equatorial angles.
		equatorial: isPlanetScale,
		validityStart,
		validityEnd,
		orbitalSource: parseOrbitalSource(orbit.source),
		...(isParabolic ? { q: orbit.q, tp: orbit.tp } : {}),
		...(satrec ? { satrec } : {})
	};

	const parentPos = loader.positions.get(orbit.parent_naif_id) ?? [0, 0, 0];
	const offset = satrec
		? sgp4PositionScene(satrec, dateToJD(date))
		: isParabolic
			? parabolicToPosition(data, date)
			: orbitalElementsToPosition(data, date);
	if (!offset) {
		console.warn(`Failed to compute position for ${targetId} (e=${data.e})`);
		return null;
	}
	const position: [number, number, number] = [
		parentPos[0] + offset[0],
		parentPos[1] + offset[1],
		parentPos[2] + offset[2]
	];

	return {
		body: { data, position, orbitElements: data, orbitCenter: parentPos },
		zone: global.sbdb?.class ?? null
	};
}

/** True if parentId is a top-level parent (SSB or Sun), not a planetary system. */
function isTopLevelParent(parentId: string): boolean {
	return parentId === 'naif-0' || parentId === 'naif-10';
}

export class ContextManager {
	private readonly childrenByParent = new Map<string, Set<string>>();
	readonly bodiesById = new Map<string, PositionedBody>();
	/** Max semi-major axis (AU) of moons per parent body ID. Used to gate point-cloud visibility. */
	private readonly moonMaxAByParent = new Map<string, number>();

	// --- Reactive loading state ---
	loading = $state(true);
	error = $state<string | null>(null);
	/** Incremented on each minor-body data flush; read by Scene.svelte to trigger point cloud rebuilds. */
	minorBodyVersion = $state(0);
	/**
	 * Providers that have contributed at least one body to the loaded scene.
	 * Reassigned (not mutated) on new arrivals so `$derived` consumers — the
	 * bottom-right attribution bar — recompute. `OrbitalSource.UNKNOWN` is
	 * never added; pre-v3 chunks with no source byte stay silent rather than
	 * showing a misleading "Unknown" label.
	 */
	orbitSources = $state(new Set<OrbitalSource>());
	/**
	 * Per-body texture credits, populated as `loadSystemData` lands each
	 * system's `systems/{bary}.json`. Drives both the bar (dedup'd org set for
	 * the focused system) and the popover (full list of every loaded texture
	 * with source URL + optional description). Bump `textureCreditsVersion`
	 * whenever a new entry lands so `$derived` consumers re-read.
	 */
	textureCredits = new Map<string, TextureCredit>();
	textureCreditsVersion = $state(0);

	// --- Non-reactive data (only read from renderer/construction, never from Svelte templates) ---
	majorBodies: PositionedBody[] = [];
	asteroidBodiesByZone = new Map<string, PositionedBody[]>();
	spacecraftByParent = new Map<string, PositionedBody[]>();
	/**
	 * Chebyshev polynomial ephemeris for SPICE-sourced major bodies. Null until
	 * the metadata.json fetch in `load()` resolves; stays null if the export
	 * ships no chebyshev block.
	 */
	chebStore: ChebyshevStore | null = null;

	/**
	 * Rolling past-position trails for every chebyshev-tracked body, keyed by
	 * string id. Populated during `ChunkLoader.process` (one orbital period of
	 * initial history) and advanced every frame by `advanceTrailBuffers`.
	 * Planets reference their barycenter's entry here via `PositionedBody.trailBuffer`.
	 */
	chebBuffers = new Map<string, TrailBuffer>();

	/** Zones/groups that received new data since last rebuild. Cleared by the consumer. */
	dirtyAsteroidZones = new Set<string>();
	dirtySpacecraftGroups = new Set<string>();

	// --- Visibility state (plain mutable: written from useTask every frame) ---
	/**
	 * Currently focused body. Reactive so the attribution bar can show texture
	 * credits for standalone bodies (asteroids like Bennu, dwarf planets like
	 * Ceres) that aren't part of a loaded planetary system.
	 */
	focusedBodyId = $state<string>('naif-10');
	isZoomedIn: boolean = false;
	private lastRecomputeDist = -1;
	/**
	 * Always set from focused body — drives moon visibility regardless of zoom.
	 * Reactive so the attribution bar can derive the active imagery credits
	 * from whichever planetary system the camera is in.
	 */
	focusedSystemId = $state<string | null>(null);
	/** Set only when zoomed in — drives hiding of other systems. */
	activeSystemId: string | null = null;
	private cameraDistThreeJS = 0;
	// Cached scaled thresholds — recomputed in updateViewport() on canvas resize.
	private scaledPlanetary = PLANETARY_DISTANCE_RATIO_THRESHOLDS;
	private scaledSystem = SYSTEM_DISTANCE_RATIO_THRESHOLDS;
	/** IDs of moons allowed FULL visibility after the crowding cap is applied. */
	private fullMoonIds = new Set<string>();
	/** Per-frame cache for getMoonVisibility, cleared in updateCamera. */
	private moonVisibilityCache = new Map<string, VISIBILITY>();

	/**
	 * Advance every chebyshev trail buffer to `jd`. For each buffer, samples
	 * chebyshev positions at step-day intervals and appends them; a big jump
	 * (forward past one period, or any reversal) clears and re-seeds from the
	 * new jd. Must be called after `chebStore.ensure(jd)` so the underlying
	 * chunks are available.
	 */
	advanceTrailBuffers(jd: number): void {
		const store = this.chebStore;
		if (!store) return;
		for (const [targetId, buffer] of this.chebBuffers) {
			const last = buffer.newestJd;
			const dt = jd - last;
			// Empty buffer, time reversed, or jump > one period: re-seed.
			if (!isFinite(last) || dt < 0 || dt > buffer.stepDays * buffer.capacity) {
				buffer.clear();
				populateTrailBuffer(buffer, store, targetId, jd);
				continue;
			}
			if (dt < buffer.stepDays) continue;
			// Append at canonical multiples of stepDays from `last`; bounded by
			// capacity so one oversized frame never does more work than a full
			// re-seed would.
			const steps = Math.min(Math.floor(dt / buffer.stepDays), buffer.capacity);
			for (let k = 1; k <= steps; k++) {
				const t = last + k * buffer.stepDays;
				const p = store.positionScene(targetId, t);
				if (p) buffer.append(t, p[0], p[1], p[2]);
			}
		}
	}

	/**
	 * Look up any body by ID.
	 *
	 * `zone` is an optional hint. When provided the search is restricted to
	 * that zone — use it from per-zone iteration paths (chunk reconciliation,
	 * picking results) where you already know which bucket the body lives in.
	 * The zone string is the same key the body was filed under: a `naif-X`
	 * parent id for spacecraft groups, or an OrbitClass enum name (e.g. `MBA`)
	 * for asteroid zones; we probe both maps so callers don't have to
	 * disambiguate.
	 *
	 * Without a hint: bodiesById → spacecraftByParent → asteroidBodiesByZone.
	 * Spacecraft come before asteroid zones because there are far fewer
	 * groups (a handful of parents vs. ~20 zones with thousands of bodies),
	 * so the linear scan finishes faster on a miss.
	 */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		const major = this.bodiesById.get(id);
		if (major) return major;
		if (zone !== undefined) {
			return (
				this.spacecraftByParent.get(zone)?.find((b) => b.data.id === id) ??
				this.asteroidBodiesByZone.get(zone)?.find((b) => b.data.id === id)
			);
		}
		for (const bodies of this.spacecraftByParent.values()) {
			const hit = bodies.find((b) => b.data.id === id);
			if (hit) return hit;
		}
		for (const bodies of this.asteroidBodiesByZone.values()) {
			const hit = bodies.find((b) => b.data.id === id);
			if (hit) return hit;
		}
		return undefined;
	}

	async load(date: Date, targetId?: string): Promise<void> {
		try {
			// Kick off moons + metadata fetches immediately, in parallel with major processing.
			// Once metadata arrives, fire all chunk prefetches so they're cached before Phase 2 starts.
			ChunkLoader.prefetch('moons', 0, 0);
			// Tiny one-shot fetch — IAU nutation/precession angles for body rotation.
			// Fire-and-forget; rotation falls back to the first-order model until it lands.
			loadNutPrecAngles();
			const metadataPromise = fetchMetadata();

			const minorChunkArgsPromise = metadataPromise.then((metadata) => {
				const args: { zone: string; zoom: number; part: number; time: string | null }[] = [];
				for (const [zone, zoneData] of Object.entries(metadata.zones)) {
					if (zone === 'major' || zone === 'moons') continue;
					for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms)) {
						const zoom = Number(zoomStr);
						// Time-segmented zones (earth) ship one chunk set per ISO date —
						// pick the snapshot nearest the simulated time so SGP4's tight
						// validity window covers it. Flat zones use a single set.
						const time = isTimeSegmented(zoomData) ? snapshotDate(zoomData, date) : null;
						for (let part = 0; part < Math.min(zoomData.parts, 20); part++) {
							args.push({ zone, zoom, part, time });
							ChunkLoader.prefetch(zone, zoom, part, time);
						}
					}
				}
				return args;
			});

			// Chebyshev must be ready before we process major/moons — those zones
			// contain the SPICE-sourced bodies whose positions we take from the
			// polynomials. No fallback: if the export carries a chebyshev block,
			// we wait.
			const chebPromise = metadataPromise.then(async (metadata) => {
				if (!metadata.chebyshev) return null;
				const store = new ChebyshevStore(metadata.chebyshev);
				await store.ensure(dateToJD(date)).done;
				return store;
			});
			this.chebStore = await chebPromise;
			const loader = new ChunkLoader(this.chebStore, this.chebBuffers);

			// Phase 1: majors — load, register, and start rendering immediately
			const major: PositionedBody[] = [];
			major.push(...(await loader.process('major', 0, 0, date)));
			major.push(...(await loader.process('moons', 0, 0, date)));

			this.addBodies(major);

			const pendingAsteroids = new Map<string, PositionedBody[]>();
			const pendingSpacecraft = new Map<string, PositionedBody[]>();
			// Placeholders for URL-loaded targets (one per session): when the real
			// chunk lands the entry's data/position fields are mutated in place so
			// the BodyObject the renderer kept holds onto fresh elements without us
			// needing to reseat references anywhere.
			const placeholderById = new Map<string, PositionedBody>();

			const flush = () => {
				this.asteroidBodiesByZone = new Map(pendingAsteroids);
				this.spacecraftByParent = new Map(pendingSpacecraft);
				this.minorBodyVersion++;
			};

			// If the target body wasn't in majors/moons, resolve it from the global
			// object file and route it into the same per-zone store its chunk will
			// land in — keeps a single source of truth and lets phase 2 reconcile
			// in place when the chunk arrives.
			if (targetId && !this.getBody(targetId)) {
				const placeholder = await createPlaceholderBody(targetId, date, loader);
				if (placeholder) {
					const { body, zone } = placeholder;
					const type = body.data.objectType;
					if (type === ObjectType.SPACECRAFT || type === ObjectType.DEBRIS) {
						const key = body.data.parentId;
						pendingSpacecraft.set(key, [...(pendingSpacecraft.get(key) ?? []), body]);
						placeholderById.set(body.data.id, body);
						this.dirtySpacecraftGroups.add(key);
					} else if (zone) {
						pendingAsteroids.set(zone, [...(pendingAsteroids.get(zone) ?? []), body]);
						placeholderById.set(body.data.id, body);
						this.dirtyAsteroidZones.add(zone);
					} else {
						// Major / undocumented / wikidata-only — no zone to route into,
						// fall back to bodiesById so getBody() still finds it.
						this.addBodies([body]);
					}
					this.recordOrbitSources([body]);
					flush();
				}
			}

			this.majorBodies = major.filter(
				(b) =>
					b.data.objectType !== ObjectType.BARYCENTER &&
					b.data.objectType !== ObjectType.LAGRANGE_POINT
			);
			this.loading = false;

			// Phase 2: minors — load in background, flush to reactive state periodically
			// minorChunkArgsPromise has been running in parallel; files are likely cached already
			const minorChunkArgs = await minorChunkArgsPromise;

			const intervalId = setInterval(flush, 500);

			try {
				await Promise.all(
					minorChunkArgs.map(({ zone, zoom, part, time }) =>
						loader.process(zone, zoom, part, date, time).then((chunk) => {
							this.recordOrbitSources(chunk);
							for (const b of chunk) {
								const placeholder = placeholderById.get(b.data.id);
								if (placeholder) {
									// Mutate in place so the renderer's BodyObject keeps a
									// stable PositionedBody ref. Per-zone dirty marker is
									// already set from placeholder routing; bumping it again
									// here ensures the worker re-packs with the fresh satrec.
									placeholder.data = b.data;
									placeholder.position = b.position;
									placeholder.orbitElements = b.orbitElements;
									placeholder.orbitCenter = b.orbitCenter;
									placeholder.trailBuffer = b.trailBuffer;
									placeholderById.delete(b.data.id);
									if (b.data.objectType === ObjectType.SPACECRAFT) {
										this.dirtySpacecraftGroups.add(b.data.parentId);
									} else {
										this.dirtyAsteroidZones.add(zone);
									}
									continue;
								}
								if (b.data.objectType === ObjectType.SPACECRAFT) {
									const list = pendingSpacecraft.get(b.data.parentId) ?? [];
									list.push(b);
									pendingSpacecraft.set(b.data.parentId, list);
									this.dirtySpacecraftGroups.add(b.data.parentId);
								} else {
									const list = pendingAsteroids.get(zone) ?? [];
									list.push(b);
									pendingAsteroids.set(zone, list);
									this.dirtyAsteroidZones.add(zone);
								}
							}
						})
					)
				);
			} finally {
				clearInterval(intervalId);
				flush();
			}
		} catch (e) {
			this.loading = false;
			throw e;
		}
	}

	addBodies(bodies: PositionedBody[]): void {
		for (const b of bodies) {
			this.bodiesById.set(b.data.id, b);

			const set = this.childrenByParent.get(b.data.parentId) ?? new Set<string>();
			set.add(b.data.id);
			this.childrenByParent.set(b.data.parentId, set);
			if (b.data.objectType === ObjectType.MOON) {
				const prev = this.moonMaxAByParent.get(b.data.parentId) ?? 0;
				if (b.data.a > prev) this.moonMaxAByParent.set(b.data.parentId, b.data.a);
			}
		}
		this.recordOrbitSources(bodies);
	}

	/**
	 * Fold each body's `orbitalSource` into the reactive set. Reassigns on new
	 * entries so `$derived` consumers recompute; no-op when everything in the
	 * batch is already known (keeps minor-body chunk flushes cheap).
	 */
	recordOrbitSources(bodies: PositionedBody[]): void {
		let added = false;
		for (const b of bodies) {
			const src = b.data.orbitalSource;
			if (src === OrbitalSource.UNKNOWN || this.orbitSources.has(src)) continue;
			this.orbitSources.add(src);
			added = true;
		}
		if (added) this.orbitSources = new Set(this.orbitSources);
	}

	/**
	 * Record the texture attribution for a body. Idempotent by `bodyId` so
	 * revisiting a system doesn't bump the version spuriously.
	 */
	registerTextureCredit(credit: TextureCredit): void {
		if (this.textureCredits.has(credit.bodyId)) return;
		this.textureCredits.set(credit.bodyId, credit);
		this.textureCreditsVersion++;
	}

	/**
	 * Call from resize() in SceneRenderer whenever the canvas dimensions change.
	 * Recomputes scaled thresholds (FULL and FAR scale linearly; CLOSE is geometric and unchanged).
	 */
	updateViewport(height: number): void {
		const sf = (height / REFERENCE_VIEWPORT_HEIGHT) ** 1.5;
		const scale = (base: typeof PLANETARY_DISTANCE_RATIO_THRESHOLDS) => ({
			...base,
			[VISIBILITY.FULL]: base[VISIBILITY.FULL] * sf,
			[VISIBILITY.FAR]: base[VISIBILITY.FAR] * sf
		});
		this.scaledPlanetary = scale(PLANETARY_DISTANCE_RATIO_THRESHOLDS);
		this.scaledSystem = scale(SYSTEM_DISTANCE_RATIO_THRESHOLDS);
	}

	/** Call from useTask every frame. */
	updateCamera(dist: number): void {
		this.cameraDistThreeJS = dist;
		this.moonVisibilityCache.clear();
		const zoomed = dist <= ZOOM_THRESHOLD_AU * AU_SCALE;
		if (zoomed !== this.isZoomedIn) {
			this.isZoomedIn = zoomed;
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemId : null;
		}
		// Only recompute when distance changes by more than 0.5% — avoids a filter+sort every frame
		if (Math.abs(dist - this.lastRecomputeDist) > this.lastRecomputeDist * 0.005 + 0.001) {
			this.lastRecomputeDist = dist;
			this.recomputeFullMoons();
		}
	}

	setFocused(body: PositionedBody): void {
		if (body.data.id !== this.focusedBodyId) {
			this.focusedBodyId = body.data.id;
			// A planetary barycenter IS the system root (planets/moons are its children),
			// but the SSB (naif-0) is top-level, not a system.
			const isSystemBarycenter =
				body.data.objectType === ObjectType.BARYCENTER &&
				isTopLevelParent(body.data.parentId) &&
				!isTopLevelParent(body.data.id);
			const isTopLevel =
				body.data.objectType === ObjectType.STAR ||
				(!isSystemBarycenter && isTopLevelParent(body.data.parentId));
			let sysId: string | null;
			if (isSystemBarycenter) {
				sysId = body.data.id;
			} else if (isTopLevel) {
				sysId = null;
			} else {
				// parentId is either the system barycenter (e.g. Earth's parent is naif-3) or
				// a system member one level deeper (e.g. an Earth satellite's parent is naif-399,
				// whose parent is naif-3). Satellites aren't recorded as barycenter children
				// — too many — so resolve by walking up via bodiesById instead.
				const parent = this.bodiesById.get(body.data.parentId);
				sysId =
					parent && !isTopLevelParent(parent.data.parentId)
						? parent.data.parentId
						: body.data.parentId;
			}
			this.focusedSystemId = sysId;
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemId : null;
			this.lastRecomputeDist = -1; // force recompute on next updateCamera
			this.recomputeFullMoons();
		}
	}

	/** Ratio-based visibility for a moon. Gated on the focused system (no zoom threshold). */
	getMoonVisibility(moon: PositionedBody): VISIBILITY {
		const cached = this.moonVisibilityCache.get(moon.data.id);
		if (cached !== undefined) return cached;
		let vis: VISIBILITY;
		if (!this.isInFocusedSystem(moon.data.parentId)) {
			vis = VISIBILITY.HIDE;
		} else {
			const ratio = this.cameraDistThreeJS / AU_SCALE / moon.data.a; // Three.js units → AU
			const isFocused = moon.data.id === this.focusedBodyId;
			vis = computeVisibilityFromRatio(
				ratio,
				this.scaledPlanetary,
				FOCUSED_FULL_MULTIPLIER_MOON,
				isFocused
			);
			// Crowding cap: demote FULL → CAPPED if not in the top-N set
			if (vis === VISIBILITY.FULL && !this.fullMoonIds.has(moon.data.id) && !isFocused)
				vis = VISIBILITY.CAPPED;
		}
		this.moonVisibilityCache.set(moon.data.id, vis);
		return vis;
	}

	/**
	 * Recomputes which moons qualify for FULL visibility, capped at MAX_FULL_MOONS.
	 * Among moons that pass the ratio threshold, only the closest to their parent (smallest a) win.
	 * Called every frame from updateCamera and on focus change from setFocused.
	 */
	private recomputeFullMoons(): void {
		this.fullMoonIds.clear();
		const sysId = this.focusedSystemId;
		if (!sysId) return;
		const camDistAU = this.cameraDistThreeJS / AU_SCALE;
		const children: PositionedBody[] = [];
		for (const id of this.childrenByParent.get(sysId) ?? []) {
			const b = this.bodiesById.get(id);
			if (
				b &&
				b.data.objectType === ObjectType.MOON &&
				camDistAU / b.data.a <= this.scaledPlanetary[VISIBILITY.FULL]
			)
				children.push(b);
		}
		children
			.sort((a, b) => a.data.a - b.data.a)
			.slice(0, MAX_FULL_MOONS)
			.forEach((m) => this.fullMoonIds.add(m.data.id));
	}

	/**
	 * Whether to show the point-cloud for a moon group (by parent ID).
	 * Gated on the focused system and ratio to outermost moon (no zoom threshold).
	 */
	isMoonGroupVisible(parentId: string): boolean {
		if (!this.isInFocusedSystem(parentId)) return false;
		const maxA = this.moonMaxAByParent.get(parentId);
		if (!maxA) return false;
		const ratio = this.cameraDistThreeJS / AU_SCALE / maxA;
		return ratio <= this.scaledPlanetary[VISIBILITY.FAR];
	}

	/**
	 * Whether a body orbits within a planetary system (not directly around SSB/Sun).
	 * True for moons, planet-orbiting spacecraft, etc.
	 */
	isSystemBody(body: PositionedBody): boolean {
		if (isTopLevelParent(body.data.parentId)) return false;
		const parent = this.bodiesById.get(body.data.parentId);
		return parent?.data.objectType !== ObjectType.BARYCENTER;
	}

	/**
	 * Distance-ratio based visibility for non-moon, non-star bodies.
	 * Bodies orbiting a planet (spacecraft, debris) are gated on the focused system,
	 * like moons. Sun-orbiting bodies use the solar-orbit semi-major axis ratio.
	 * Spacecraft use distance to focused body (like moons) so they appear/disappear
	 * uniformly by zoom level; planets use distance to the body itself.
	 */
	getPlanetVisibility(body: PositionedBody, camDistThreeJS: number): VISIBILITY {
		// Planet-orbiting bodies: only visible when their system is focused.
		if (this.isSystemBody(body)) {
			if (!this.isInFocusedSystem(body.data.parentId)) return VISIBILITY.HIDE;
			return VISIBILITY.FULL;
		}

		// Sun-orbiting: walk up to the barycenter to find solar-orbit semi-major axis.
		let refA = body.data.a;
		if (!isTopLevelParent(body.data.parentId)) {
			const parent = this.bodiesById.get(body.data.parentId);
			if (parent?.data.a) refA = parent.data.a;
		}
		if (!refA || refA < 0) {
			if (refA >= 0 && body.data.e < 0.9) {
				console.log(
					`No semi-major axis available for body ${body.data.id} (${body.data.name}), falling back to FULL visibility`
				);
			}
			return VISIBILITY.FULL;
		}
		// Spacecraft use distance to focused body (uniform visibility by zoom level),
		// planets use distance to the body itself.
		const dist =
			body.data.objectType === ObjectType.SPACECRAFT ? this.cameraDistThreeJS : camDistThreeJS;
		const isFocused = body.data.id === this.focusedBodyId;
		return computeVisibilityFromRatio(
			dist / AU_SCALE / refA,
			this.scaledSystem,
			FOCUSED_FULL_MULTIPLIER_SPACECRAFT,
			isFocused
		);
	}

	/** Full rendering = halo + trail. Suppressed for out-of-system bodies when zoomed in. */
	hasFullRendering(body: PositionedBody): boolean {
		const sysId = this.activeSystemId;
		if (!sysId) return true;
		return this.isInActiveSystem(
			isTopLevelParent(body.data.parentId) ? body.data.id : body.data.parentId
		);
	}

	/**
	 * Whether a spacecraft point-cloud group should be shown.
	 * Sun-level groups (parentId=0 or parent is STAR) are always visible.
	 * Planet-orbiting groups are only visible when in the active system.
	 */
	isSpacecraftGroupVisible(groupParentId: string): boolean {
		const sysId = this.activeSystemId;
		if (isTopLevelParent(groupParentId)) return !sysId;
		const parent = this.bodiesById.get(groupParentId);
		if (parent?.data.objectType === ObjectType.STAR) return !sysId;
		if (!sysId) return false;
		if (groupParentId === sysId) return true;
		return this.childrenByParent.get(sysId)?.has(groupParentId) ?? false;
	}

	/**
	 * Whether an asteroid zone's point-cloud should be visible.
	 * Compares camera distance (AU) to the zone's semi-major axis range.
	 * Zones without a defined range (parabolic, unclassified) are always visible.
	 */
	isAsteroidGroupVisible(zone: string): boolean {
		if (this.activeSystemId) return false;
		const range = ZONE_A_RANGE[zone];
		if (!range) return true;
		const camDistAU = this.cameraDistThreeJS / AU_SCALE;
		const ratio = camDistAU / range.maxA;
		// reduce clutter by lowering threshold a bit
		return ratio <= this.scaledSystem[VISIBILITY.FAR] / 3;
	}

	/** Max orbital semi-major axis (AU) of moons in a system. Used to size the shadow camera frustum. */
	getSystemExtent(sysId: string): number {
		return this.moonMaxAByParent.get(sysId) ?? 0.01;
	}

	isInActiveSystem(parentId: string): boolean {
		return this.isInSystem(parentId, this.activeSystemId);
	}

	private isInFocusedSystem(parentId: string): boolean {
		return this.isInSystem(parentId, this.focusedSystemId);
	}

	/**
	 * True when focused somewhere in the Earth-Moon system (barycenter, Earth,
	 * Moon, an Earth satellite, or a lunar orbiter — setFocused resolves all of
	 * these to naif-3). Used to gate CelesTrak attribution, which is only
	 * relevant when Earth satellites are actually on screen.
	 */
	isFocusedOnEarthSystem(): boolean {
		return this.focusedSystemId === 'naif-3';
	}

	/**
	 * True if the given parentId belongs to a system.
	 * Handles two levels: parentId === barycenter, or parentId is a direct child of the barycenter.
	 */
	private isInSystem(parentId: string, sysId: string | null): boolean {
		if (!sysId) return false;
		if (parentId === sysId) return true;
		return this.childrenByParent.get(sysId)?.has(parentId) ?? false;
	}
}
