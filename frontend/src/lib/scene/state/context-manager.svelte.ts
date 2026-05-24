import { ObjectType, ZONE_A_RANGE, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/position/chunk';
import { fetchLabels } from '$lib/fetch/position/labels';
import { OrbitalSource } from '$lib/fetch/position/format';
import { AU_SCALE } from '$lib/math/units';
import { loadSystemsGlobal } from '$lib/fetch/systems-global';
import { createPlaceholderBody } from '$lib/scene/setup/placeholder';
import { CreditsStore } from '$lib/scene/state/credits.svelte';
import { BodyIndex, isTopLevelParent } from '$lib/scene/state/bodies.svelte';
import {
	chebyshevZoneParams,
	chunkIndexForJd,
	fetchMetadata,
	isChunkIndexed,
	isDateSegmented,
	isParted,
	isProbeZone,
	probeZoneParams,
	snapshotDate
} from '$lib/fetch/metadata';
import { dateToJD } from '$lib/format/date';
import { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { ProbeStore } from '$lib/fetch/position/probes/store';
import { ZoneRefresher } from '$lib/scene/zone-refresher';
import {
	VISIBILITY,
	REFERENCE_VIEWPORT_HEIGHT,
	PLANETARY_DISTANCE_RATIO_THRESHOLDS,
	SYSTEM_DISTANCE_RATIO_THRESHOLDS,
	FOCUSED_FULL_MULTIPLIER_MOON,
	FOCUSED_FULL_MULTIPLIER_SPACECRAFT,
	MAX_FULL_MOONS,
	computeVisibilityFromRatio,
	ZOOM_THRESHOLD_AU
} from '$lib/scene/visibility/thresholds';

export class ContextManager {
	/** Body store: every loaded `PositionedBody`, parent/child graph, dirty
	 *  zone markers, and version counters for reactive consumers. */
	bodies = new BodyIndex();

	// --- Reactive loading state ---
	loading = $state(true);
	error = $state<string | null>(null);
	/** Attribution state: per-body imagery credits, skybox credit, orbit-source set. */
	credits = new CreditsStore();

	/**
	 * Chebyshev polynomial ephemeris for SPICE-sourced major bodies. Null until
	 * the metadata.json fetch in `load()` resolves; stays null if the export
	 * ships no chebyshev block.
	 */
	chebStore: ChebyshevStore | null = null;
	/**
	 * Per-zone probe sub-chunks (Kepler-pure / Kepler-drift / Chebyshev). Null
	 * until metadata resolves; stays null when the export ships no probe
	 * zones. The renderer's per-frame update path consults it for any body
	 * whose `orbitalSource === SPICE_PROBE`.
	 */
	probeStore: ProbeStore | null = null;

	/** Zones/groups that received new data since last rebuild. Cleared by the consumer. */
	dirtyAsteroidZones = new Set<string>();
	dirtySpacecraftGroups = new Set<string>();

	/** Hot-reload driver for time-segmented (Earth SGP4 sats) and chunk-indexed
	 *  (moons Method-C secular elements) zones. Created at the end of load()
	 *  once the loader and metadata are available. */
	private refresher: ZoneRefresher | null = null;

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
	// Plain mirrors of the reactive focus fields above. Hot per-frame loops
	// (visibility, sphere/texture LOD, ring shaders) read these instead of the
	// $state-tracked versions — in dev mode every $state getter fires a
	// reactive-source tag + `get_proxied_value` trap, and the per-body loops
	// turned that into the dominant cost.
	private focusedBodyIdPlain: string = 'naif-10';
	private focusedSystemIdPlain: string | null = null;
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

	/** Look up any body by ID. Carve-out delegate — see {@link BodyIndex.getBody}. */
	getBody(id: string, zone?: string): PositionedBody | undefined {
		return this.bodies.getBody(id, zone);
	}

	async load(date: Date, targetId?: string): Promise<void> {
		try {
			// Tiny one-shot fetch — IAU nutation/precession angles for body rotation
			// + per-body GMs used by chebyshev trail-buffer sizing. Fire-and-forget;
			// rotation falls back to the first-order model and trail buffers stay
			// uninitialized until it lands.
			loadSystemsGlobal();
			const jd = dateToJD(date);
			const metadataPromise = fetchMetadata();
			// Moons prefetch is owned by ZoneRefresher (chunk-indexed branch);
			// it warms `[idx-1, idx, idx+1]` at construction. The flat-zone case
			// (no chunk index) is handled here as a one-shot HTTP warm.
			metadataPromise.then((metadata) => {
				const moons = metadata.position.zones.moons;
				if (!moons || isProbeZone(moons)) return;
				const moonsZoom = moons.zooms[0];
				if (moonsZoom && isParted(moonsZoom)) {
					ChunkLoader.prefetch('moons', 0, 0, null);
				}
			});

			const minorChunkArgsPromise = metadataPromise.then((metadata) => {
				const args: {
					zone: string;
					zoom: number;
					part: number;
					time: string | null;
					parentIdType: string;
				}[] = [];
				for (const [zone, zoneData] of Object.entries(metadata.position.zones)) {
					if (zone === 'major' || zone === 'moons') continue;
					// `spacecraft` was the legacy Sun-orbiter Kepler-fallback zone.
					// Its objects now ship through the probes export (mixed
					// Kepler-with-drift + Chebyshev sub-chunks); skip the zone
					// here even if a stale manifest still lists it.
					if (zone === 'spacecraft') continue;
					// Probe zones load through ProbeStore, not the elements ChunkLoader.
					if (isProbeZone(zoneData)) continue;
					const parentIdType = zoneData.parent_id_type ?? 'naif';
					for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms)) {
						const zoom = Number(zoomStr);
						// Chebyshev zones (`shape: chunked`) load through ChebyshevStore,
						// not through ChunkLoader — skip them here.
						if (zoomData.shape === 'chunked') continue;
						// Date-segmented zones (earth) ship one chunk set per ISO date —
						// pick the snapshot nearest the simulated time so SGP4's tight
						// validity window covers it. Static-parted zones use a single set.
						const time = isDateSegmented(zoomData) ? snapshotDate(zoomData, date) : null;
						for (let part = 0; part < Math.min(zoomData.parts, 20); part++) {
							args.push({ zone, zoom, part, time, parentIdType });
							ChunkLoader.prefetch(zone, zoom, part, time);
						}
					}
				}
				return args;
			});

			// Chebyshev must be ready before we process major/moons — the zones
			// it covers (Sun/planets/dwarves at major, perturbers at
			// major_asteroids, whitelisted moons at moons/<parent>) supply the
			// only positions for those bodies. No fallback: if the export
			// carries chebyshev zones, we wait.
			const chebPromise = metadataPromise.then(async (metadata) => {
				const params = chebyshevZoneParams(metadata);
				if (params.size === 0) return null;
				const store = new ChebyshevStore(params);
				await store.ensure(jd).done;
				return store;
			});
			// Probes lag chebyshev — fit-center body positions must be in
			// loader.positions before processProbes runs, and those come from
			// the chebyshev pass below.
			const probePromise = metadataPromise.then(async (metadata) => {
				const params = probeZoneParams(metadata);
				if (params.size === 0) return null;
				console.log(
					`ProbeStore: ${params.size} zone(s) from metadata:\n` +
						Array.from(params)
							.map(
								([zone, p]) =>
									`  ${zone}: chunks=${p.chunks} chunk_years=${p.chunk_years} ` +
									`fit_center=naif-${p.fit_center_naif_id} float64=${p.float64_coeffs}`
							)
							.join('\n')
				);
				const missingCenter = Array.from(params).filter(
					([, p]) => p.fit_center_naif_id === undefined
				);
				if (missingCenter.length > 0) {
					console.warn(
						`ProbeStore: ${missingCenter.length} zone(s) missing fit_center_naif_id in metadata ` +
							`— re-export to refresh: ${missingCenter.map(([z]) => z).join(', ')}`
					);
				}
				const store = new ProbeStore(params);
				await store.ensure(jd).done;
				return store;
			});
			const metadata = await metadataPromise;
			this.chebStore = await chebPromise;
			this.probeStore = await probePromise;
			const loader = new ChunkLoader(this.chebStore);

			// Phase 1: majors — load, register, and start rendering immediately.
			//
			// Bodies arrive from four sources, in dependency order:
			//   - Chebyshev (`ChunkLoader.processChebyshev`): Sun, planets/
			//     dwarves with SPK kernels, perturber asteroids, whitelisted
			//     moons. Runs first so its barycenters/Sun land in
			//     `loader.positions` before kepler-fallback dwarves (which
			//     parent on those barycenters) try to resolve.
			//   - major/1 elements: horizons-sourced majors not in chebyshev
			//     — in practice this catches dwarf planets with Horizons
			//     ephemerides but no SPK kernel.
			//   - major/2 elements: SBDB-only dwarves (Eris, Makemake,
			//     Quaoar, …) that aren't in any SPK kernel either.
			//   - moons elements: non-whitelisted moons (Method-C secular
			//     elements, chunk-indexed).
			//
			// Zoom 0 is reserved for chebyshev — kepler fallbacks live at
			// higher zooms so the per-zoom shape stays single-payload.
			const major: PositionedBody[] = [];
			let cachedLabels: Awaited<ReturnType<typeof fetchLabels>> | null = null;
			if (this.chebStore) {
				cachedLabels = await fetchLabels();
				major.push(...loader.processChebyshev(date, cachedLabels));
			}
			if (this.probeStore) {
				cachedLabels ??= await fetchLabels();
				major.push(...loader.processProbes(this.probeStore, date, cachedLabels));
			}
			const majorZone = metadata.position.zones.major;
			if (majorZone && !isProbeZone(majorZone)) {
				for (const zoom of [1, 2] as const) {
					const zoomData = majorZone.zooms[String(zoom)];
					if (zoomData && isParted(zoomData)) {
						for (let p = 0; p < zoomData.parts; p++) {
							major.push(...(await loader.process('major', zoom, p, date)));
						}
					}
				}
			}
			const moonsZone = metadata.position.zones.moons;
			const moonsZoom = moonsZone && !isProbeZone(moonsZone) ? moonsZone.zooms[0] : undefined;
			const moonsTime =
				moonsZoom && isChunkIndexed(moonsZoom) ? String(chunkIndexForJd(moonsZoom, jd)) : null;
			if (moonsZoom) {
				major.push(...(await loader.process('moons', 0, 0, date, moonsTime)));
			}

			this.bodies.addBodies(major);
			this.credits.recordOrbitSources(major);

			const pendingAsteroids = new Map<string, Map<string, PositionedBody>>();
			const pendingSpacecraft = new Map<string, Map<string, PositionedBody>>();
			// Placeholders for URL-loaded targets (one per session): when the real
			// chunk lands the entry's data/position fields are mutated in place so
			// the BodyObject the renderer kept holds onto fresh elements without us
			// needing to reseat references anywhere.
			const placeholderById = new Map<string, PositionedBody>();

			const flush = () => {
				// Re-wrap each inner Map so the outer reference changes for any
				// reactive observers — inner refs stay stable for in-place updates.
				const cloneOuter = <K, V>(m: Map<K, V>): Map<K, V> => new Map(m);
				this.bodies.asteroidBodiesByZone = cloneOuter(pendingAsteroids);
				this.bodies.spacecraftByParent = cloneOuter(pendingSpacecraft);
				this.bodies.minorBodyVersion++;
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
						let bucket = pendingSpacecraft.get(key);
						if (!bucket) pendingSpacecraft.set(key, (bucket = new Map()));
						bucket.set(body.data.id, body);
						placeholderById.set(body.data.id, body);
						this.bodies.dirtySpacecraftGroups.add(key);
					} else if (zone) {
						let bucket = pendingAsteroids.get(zone);
						if (!bucket) pendingAsteroids.set(zone, (bucket = new Map()));
						bucket.set(body.data.id, body);
						placeholderById.set(body.data.id, body);
						this.bodies.dirtyAsteroidZones.add(zone);
					} else {
						// Major / undocumented / wikidata-only — no zone to route into,
						// fall back to bodiesById so getBody() still finds it.
						this.bodies.addBodies([body]);
					}
					this.credits.recordOrbitSources([body]);
					flush();
				}
			}

			// Probes ride bodiesById (so getBody / URL focus / placeholder routing
			// works) but are excluded from `majorBodies` so `buildScene` doesn't
			// build a sphere + orbit line for each on first paint. The hot
			// per-frame iteration loops (visibility, sphere LOD, texture LOD,
			// ring shaders) walk `bodyObjects` which only contains promoted
			// entries — keeping the long tail of probes out of that set keeps
			// the loops short. On focus, `ensureBodyObjects` builds the full
			// visual representation.
			this.bodies.majorBodies = major.filter(
				(b) =>
					b.data.objectType !== ObjectType.BARYCENTER &&
					b.data.objectType !== ObjectType.LAGRANGE_POINT &&
					b.data.orbitalSource !== OrbitalSource.SPICE_PROBE
			);
			this.loading = false;

			// Phase 2: minors — load in background, flush to reactive state periodically
			// minorChunkArgsPromise has been running in parallel; files are likely cached already
			const minorChunkArgs = await minorChunkArgsPromise;

			const intervalId = setInterval(flush, 500);

			try {
				await Promise.all(
					minorChunkArgs.map(({ zone, zoom, part, time, parentIdType }) =>
						loader.process(zone, zoom, part, date, time, parentIdType).then((chunk) => {
							this.credits.recordOrbitSources(chunk);
							for (const b of chunk) {
								const placeholder = placeholderById.get(b.data.id);
								if (placeholder) {
									// Mutate in place so the renderer's BodyObject keeps a
									// stable PositionedBody ref. Per-zone dirty marker is
									// already set from placeholder routing; bumping it again
									// here ensures the worker re-packs with the fresh satrec.
									placeholder.data = b.data;
									placeholder.position = b.position;
									// Optional fields stay set if the chunk doesn't carry
									// them — chunk.ts leaves orbitElements/orbitCenter unset
									// for non-major bodies, but the placeholder's orbitCenter
									// array is what the per-frame loop mutates to keep the
									// focused sat's orbit line tracking parent motion.
									if (b.orbitElements !== undefined) placeholder.orbitElements = b.orbitElements;
									if (b.orbitCenter !== undefined) placeholder.orbitCenter = b.orbitCenter;
									placeholderById.delete(b.data.id);
									if (b.data.objectType === ObjectType.SPACECRAFT) {
										this.bodies.dirtySpacecraftGroups.add(b.data.parentId);
									} else {
										this.bodies.dirtyAsteroidZones.add(zone);
									}
									continue;
								}
								if (b.data.objectType === ObjectType.SPACECRAFT) {
									let bucket = pendingSpacecraft.get(b.data.parentId);
									if (!bucket) pendingSpacecraft.set(b.data.parentId, (bucket = new Map()));
									bucket.set(b.data.id, b);
									this.bodies.dirtySpacecraftGroups.add(b.data.parentId);
								} else {
									let bucket = pendingAsteroids.get(zone);
									if (!bucket) pendingAsteroids.set(zone, (bucket = new Map()));
									bucket.set(b.data.id, b);
									this.bodies.dirtyAsteroidZones.add(zone);
								}
							}
						})
					)
				);
			} finally {
				clearInterval(intervalId);
				flush();
			}

			// Hot-reload driver: at this point metadataPromise has already
			// resolved (chebPromise awaited it), so this awaits a settled promise.
			this.refresher = new ZoneRefresher(this, await metadataPromise, loader, date);
		} catch (e) {
			this.loading = false;
			throw e;
		}
	}

	/** Per-frame hook called by the renderer when sim jd advances. Drives
	 *  hot-reload of time-segmented zones (Earth SGP4 sats) and chunk-indexed
	 *  zones (moons Method-C-fit elements expire each chunk). */
	refreshTick(date: Date): void {
		this.refresher?.tick(date);
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
			this.activeSystemId = this.isZoomedIn ? this.focusedSystemIdPlain : null;
		}
		// Only recompute when distance changes by more than 0.5% — avoids a filter+sort every frame
		if (Math.abs(dist - this.lastRecomputeDist) > this.lastRecomputeDist * 0.005 + 0.001) {
			this.lastRecomputeDist = dist;
			this.recomputeFullMoons();
		}
	}

	setFocused(body: PositionedBody): void {
		if (body.data.id !== this.focusedBodyIdPlain) {
			this.focusedBodyId = body.data.id;
			this.focusedBodyIdPlain = body.data.id;
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
				const parent = this.bodies.bodiesById.get(body.data.parentId);
				sysId =
					parent && !isTopLevelParent(parent.data.parentId)
						? parent.data.parentId
						: body.data.parentId;
			}
			this.focusedSystemId = sysId;
			this.focusedSystemIdPlain = sysId;
			this.activeSystemId = this.isZoomedIn ? sysId : null;
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
			const isFocused = moon.data.id === this.focusedBodyIdPlain;
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
		const sysId = this.focusedSystemIdPlain;
		if (!sysId) return;
		const camDistAU = this.cameraDistThreeJS / AU_SCALE;
		const children: PositionedBody[] = [];
		for (const id of this.bodies.getChildren(sysId) ?? []) {
			const b = this.bodies.bodiesById.get(id);
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
		const maxA = this.bodies.maxMoonA(parentId);
		if (!maxA) return false;
		const ratio = this.cameraDistThreeJS / AU_SCALE / maxA;
		return ratio <= this.scaledPlanetary[VISIBILITY.FAR];
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
		if (this.bodies.isSystemBody(body)) {
			if (!this.isInFocusedSystem(body.data.parentId)) return VISIBILITY.HIDE;
			return VISIBILITY.FULL;
		}

		// Probes carry a=0 by design — their positions come from per-sub-chunk
		// methods (kepler_pure/drift/chebyshev), not an osculating ellipse — so
		// approximate refA from the current body→parent distance (≈ semi-major
		// axis for near-circular orbits, which most probes follow once captured;
		// cruise probes parent on the Sun and end up with a heliocentric-scale
		// refA naturally).
		let refA: number;
		if (body.data.orbitalSource === OrbitalSource.SPICE_PROBE) {
			const parent = this.bodies.bodiesById.get(body.data.parentId);
			if (!parent) return VISIBILITY.FULL;
			const dx = body.position[0] - parent.position[0];
			const dy = body.position[1] - parent.position[1];
			const dz = body.position[2] - parent.position[2];
			refA = Math.sqrt(dx * dx + dy * dy + dz * dz) / AU_SCALE / 2;
		} else {
			// Sun-orbiting: walk up to the barycenter to find solar-orbit semi-major axis.
			refA = body.data.a;
			if (!isTopLevelParent(body.data.parentId)) {
				const parent = this.bodies.bodiesById.get(body.data.parentId);
				if (parent?.data.a) refA = parent.data.a;
			}
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
		const isFocused = body.data.id === this.focusedBodyIdPlain;
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
		const parent = this.bodies.bodiesById.get(groupParentId);
		if (parent?.data.objectType === ObjectType.STAR) return !sysId;
		if (!sysId) return false;
		if (groupParentId === sysId) return true;
		return this.bodies.getChildren(sysId)?.has(groupParentId) ?? false;
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

	isInActiveSystem(parentId: string): boolean {
		return this.bodies.isInSystem(parentId, this.activeSystemId);
	}

	/** True if `body` (the body itself or by parentage) belongs to `sysId`. */
	isBodyInSystem(body: PositionedBody, sysId: string): boolean {
		return body.data.id === sysId || this.bodies.isInSystem(body.data.parentId, sysId);
	}

	private isInFocusedSystem(parentId: string): boolean {
		return this.bodies.isInSystem(parentId, this.focusedSystemIdPlain);
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
}
