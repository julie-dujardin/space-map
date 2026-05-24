import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/position/chunk';
import { fetchLabels } from '$lib/fetch/position/labels';
import { OrbitalSource } from '$lib/fetch/position/format';
import { loadSystemsGlobal } from '$lib/fetch/systems-global';
import { createPlaceholderBody } from '$lib/scene/setup/placeholder';
import { CreditsStore } from '$lib/scene/state/credits.svelte';
import { BodyIndex } from '$lib/scene/state/bodies.svelte';
import { VisibilityController } from '$lib/scene/visibility/controller.svelte';
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

	/** Hot-reload driver for time-segmented (Earth SGP4 sats) and chunk-indexed
	 *  (moons Method-C secular elements) zones. Created at the end of load()
	 *  once the loader and metadata are available. */
	private refresher: ZoneRefresher | null = null;

	/** Focus state + per-frame visibility decisions. Reads body topology from
	 *  {@link BodyIndex}; the rendering side in `visibility/update.ts` reads
	 *  VISIBILITY values from here and applies them to Three.js objects. */
	visibility = new VisibilityController(this.bodies);

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
}
