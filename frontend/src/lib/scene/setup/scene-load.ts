import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/position/chunk';
import { fetchLabels } from '$lib/fetch/position/labels';
import { MinorBucket } from '$lib/fetch/position/minor-columns';
import type { ElementColumns } from '$lib/fetch/position/elements/parse';
import { OrbitalSource } from '$lib/fetch/position/format';
import { loadSystemsGlobal } from '$lib/fetch/systems-global';
import {
	chebyshevZoneParams,
	chunkIndexForJd,
	fetchMetadata,
	isChunkIndexed,
	isDateSegmented,
	isParted,
	isProbeZone,
	probeZoneParams,
	snapshotDate,
	type Metadata
} from '$lib/fetch/metadata';
import { dateToJD } from '$lib/format/date';
import { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { ProbeStore } from '$lib/fetch/position/probes/store';
import { ZoneRefresher } from '$lib/scene/zone-refresher';
import { prefetchSkyboxTiers } from '$lib/scene/objects/sky/skybox';
import { markEagerMinorsDone } from '$lib/scene/setup/load-gates';
import { createPlaceholderBody } from '$lib/scene/setup/placeholder';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { getSettings } from '$lib/state/settings.svelte';

interface MinorChunkArg {
	zone: string;
	zoom: number;
	part: number;
	time: string | null;
	parentIdType: string;
}

/**
 * Parts are uniform random shards (hash-bucketed by `Object.random_int`), so the
 * first N parts of a zoom bucket are a representative sample of the whole zone.
 * Unnamed (zoom-1) parts past this cap are split into a deferred wave that runs
 * only after the eager wave finishes, so the point cloud reaches a visually
 * representative density before the long tail competes for bandwidth. Only the
 * main belt (MBA, 133 zoom-1 parts) exceeds this today; every other zone is
 * smaller and stays fully eager.
 */
const EAGER_ZOOM1_PARTS = 13;

/**
 * Build the phase-2 chunk-fetch plan, split into an eager wave (named bodies,
 * plus a representative sample of unnamed bodies) and a deferred wave (the
 * unnamed long tail). No `ChunkLoader.prefetch` warming: firing every part up
 * front floods the connection and starves the phase-1 critical path on
 * bandwidth-bound links — the awaited `loader.process` calls fetch on demand.
 * Skips `major`/`moons` (phase 1), probe zones (ProbeStore), chebyshev.
 */
function planMinorChunks(
	metadata: Metadata,
	date: Date
): { eager: MinorChunkArg[]; deferred: MinorChunkArg[] } {
	const cap = getSettings().maxPartsPerZone;
	const eager: MinorChunkArg[] = [];
	const deferred: MinorChunkArg[] = [];
	for (const [zone, zoneData] of Object.entries(metadata.position.zones)) {
		if (zone === 'major' || zone === 'moons') continue;
		if (zone === 'spacecraft') continue;
		if (isProbeZone(zoneData)) continue;
		const parentIdType = zoneData.parent_id_type ?? 'naif';
		for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms)) {
			const zoom = Number(zoomStr);
			if (zoomData.shape === 'chunked') continue;
			// Date-segmented zones (earth): pick snapshot nearest the sim time so SGP4's window covers it.
			const time = isDateSegmented(zoomData) ? snapshotDate(zoomData, date) : null;
			const limit = cap > 0 ? Math.min(zoomData.parts, cap) : zoomData.parts;
			for (let part = 0; part < limit; part++) {
				const arg = { zone, zoom, part, time, parentIdType };
				if (zoom >= 1 && part >= EAGER_ZOOM1_PARTS) deferred.push(arg);
				else eager.push(arg);
			}
		}
	}
	return { eager, deferred };
}

/** Build the probe ephemeris store from metadata, or null when no probe zones ship. */
async function buildProbeStore(metadata: Metadata, jd: number): Promise<ProbeStore | null> {
	const params = probeZoneParams(metadata);
	if (params.size === 0) return null;
	console.log(
		`ProbeStore: ${params.size} zone(s) from metadata:\n` +
			Array.from(params)
				.map(
					([zone, p]) =>
						`  ${zone}: chunks=${p.chunks} chunk_days=${p.chunk_days} ` +
						`fit_center=naif-${p.fit_center_naif_id} float64=${p.float64_coeffs}`
				)
				.join('\n')
	);
	const missingCenter = Array.from(params).filter(([, p]) => p.fit_center_naif_id === undefined);
	if (missingCenter.length > 0) {
		console.warn(
			`ProbeStore: ${missingCenter.length} zone(s) missing fit_center_naif_id in metadata ` +
				`— re-export to refresh: ${missingCenter.map(([z]) => z).join(', ')}`
		);
	}
	const store = new ProbeStore(params);
	await store.ensure(jd).done;
	return store;
}

/**
 * Phase 1 majors, loaded in dependency order: chebyshev first (Sun + planets +
 * perturbers + whitelisted moons) so its positions are in `loader.positions`
 * before kepler-fallback dwarves try to resolve their parents; then
 * `major/1` (Horizons no-SPK), `major/2` (SBDB-only dwarves), `moons`
 * (non-whitelisted, Method-C secular).
 * Zoom 0 is reserved for chebyshev so per-zoom shape stays single-payload.
 */
async function loadMajorBodies(
	ctx: ContextManager,
	loader: ChunkLoader,
	metadata: Metadata,
	date: Date,
	jd: number
): Promise<PositionedBody[]> {
	const major: PositionedBody[] = [];
	let cachedLabels: Awaited<ReturnType<typeof fetchLabels>> | null = null;
	if (ctx.chebStore) {
		cachedLabels = await fetchLabels();
		major.push(...loader.processChebyshev(date, cachedLabels));
	}
	if (ctx.probeStore) {
		cachedLabels ??= await fetchLabels();
		major.push(...loader.processProbes(ctx.probeStore, date, cachedLabels));
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
	return major;
}

/**
 * Boot the scene's data layer: fetch metadata, build the ephemeris stores
 * (Chebyshev + probes), load the major-body chunk, route placeholders, then
 * stream the minor-body chunks in the background flushing periodically into
 * `ctx.bodies`. Writes through the manager's sub-stores; sets `loading=false`
 * once phase 1 (majors visible) completes.
 *
 * Two-phase to get first paint up before tens of thousands of asteroids land:
 *  - Phase 1 (awaited): Chebyshev + probe stores + major/moon chunks. Once
 *    these are in `bodies.majorBodies`, the renderer can build the scene.
 *  - Phase 2 (background): minor-body element chunks (asteroids, spacecraft
 *    groups). Flushes every 500ms so the point clouds grow visibly while the
 *    rest of the page is interactive.
 *
 * Caller (ContextManager.load) is responsible for resetting `loading` on
 * thrown errors — this function only sets it to false on the success path.
 */
export async function loadScene(ctx: ContextManager, date: Date, targetId?: string): Promise<void> {
	// Tiny one-shot fetch — IAU nutation/precession angles for body rotation
	// + per-body GMs used by chebyshev trail-buffer sizing. Fire-and-forget;
	// rotation falls back to the first-order model and trail buffers stay
	// uninitialized until it lands.
	performance.mark('sm-load-start');
	loadSystemsGlobal();
	const jd = dateToJD(date);
	const metadataPromise = fetchMetadata();

	// Moons prefetch is owned by ZoneRefresher (chunk-indexed branch); it
	// warms `[idx-1, idx, idx+1]` at construction. The flat-zone case (no
	// chunk index) is handled here as a one-shot HTTP warm.
	metadataPromise.then((metadata) => {
		const moons = metadata.position.zones.moons;
		if (!moons || isProbeZone(moons)) return;
		const moonsZoom = moons.zooms[0];
		if (moonsZoom && isParted(moonsZoom)) {
			ChunkLoader.prefetch('moons', 0, 0, null);
		}
	});

	// Skybox is the page background — start fetching+decoding the low tier as
	// soon as the tier list is known, rather than waiting for renderer init.
	metadataPromise.then((metadata) => {
		if (metadata.skybox) prefetchSkyboxTiers(metadata.skybox);
	});

	const minorChunkArgsPromise = metadataPromise.then((metadata) => planMinorChunks(metadata, date));

	// Chebyshev must be ready before we process major/moons — the zones it
	// covers (Sun/planets/dwarves at major, perturbers at major_asteroids,
	// whitelisted moons at moons/<parent>) supply the only positions for
	// those bodies. No fallback: if the export carries chebyshev zones, we
	// wait. Probes lag chebyshev — fit-center body positions must be in
	// loader.positions before processProbes runs, and those come from the
	// chebyshev pass above.
	const chebPromise = metadataPromise.then(async (metadata) => {
		const params = chebyshevZoneParams(metadata);
		if (params.size === 0) return null;
		const store = new ChebyshevStore(params);
		await store.ensure(jd).done;
		return store;
	});
	const probePromise = metadataPromise.then((metadata) => buildProbeStore(metadata, jd));

	const metadata = await metadataPromise;
	ctx.chebStore = await chebPromise;
	ctx.probeStore = await probePromise;
	ctx.probeCoverage = metadata.position.probe_coverage
		? new Map(Object.entries(metadata.position.probe_coverage))
		: null;
	const loader = new ChunkLoader(ctx.chebStore);

	const major = await loadMajorBodies(ctx, loader, metadata, date, jd);
	ctx.bodies.addBodies(major);
	ctx.credits.recordOrbitSources(major);

	// Labels resolve once on app start; awaited here so each MinorBucket can
	// materialize names/flags on demand without re-awaiting per chunk.
	const labels = await fetchLabels();

	// Asteroid buckets live directly on ctx.bodies; chunks are added in place and
	// the outer Map is re-wrapped on flush so reactive observers see a new ref.
	const asteroidBucket = (zone: string): MinorBucket => {
		let b = ctx.bodies.asteroidBodiesByZone.get(zone);
		if (!b) ctx.bodies.asteroidBodiesByZone.set(zone, (b = new MinorBucket(labels)));
		return b;
	};
	// Spacecraft (Earth sats / debris) stay on the AoS per-id Map path.
	const spacecraftBucket = (key: string): Map<string, PositionedBody> => {
		let b = ctx.bodies.spacecraftByParent.get(key);
		if (!b) ctx.bodies.spacecraftByParent.set(key, (b = new Map()));
		return b;
	};

	// Placeholders for URL-loaded spacecraft targets: when the real chunk lands
	// the entry's data/position are mutated in place so the renderer's held
	// BodyObject ref stays valid. (Asteroid placeholders live in MinorBucket.)
	const placeholderById = new Map<string, PositionedBody>();
	// Ids added to a bucket since the last flush — drained at flush time to feed
	// `BodyIndex.notifyBodiesAdded` so the promotion registry picks up curated
	// asteroids/spacecraft without polling.
	const addedSinceFlush = new Set<string>();

	const flush = () => {
		// Re-wrap the outer Maps so the reference changes for reactive observers
		// — the inner MinorBucket refs stay stable (mutated in place by addChunk).
		ctx.bodies.asteroidBodiesByZone = new Map(ctx.bodies.asteroidBodiesByZone);
		ctx.bodies.spacecraftByParent = new Map(ctx.bodies.spacecraftByParent);
		ctx.bodies.minorBodyVersion++;
		if (addedSinceFlush.size > 0) {
			ctx.bodies.notifyBodiesAdded([...addedSinceFlush]);
			addedSinceFlush.clear();
		}
	};

	// If the target body wasn't in majors/moons, resolve it from the global
	// object file and route it into the same per-zone store its chunk will
	// land in — keeps a single source of truth and lets phase 2 reconcile
	// in place when the chunk arrives.
	if (targetId && !ctx.getBody(targetId)) {
		// Returns the chain ancestors→target when the target's parent isn't
		// yet in `loader.positions` (e.g. moon-of-asteroid URL load before
		// phase 2). Each ancestor needs the same routing pass so it shows up
		// immediately instead of being invisible until its own chunk lands.
		// All entries go through the same per-type routing — asteroid-moons
		// are steered into `small_body_moons` so they match the regular
		// chunk-load path (PromotionRegistry's asteroid-moon auto-promote
		// picks them up and the parent asteroid along with them).
		const placeholders = await createPlaceholderBody(targetId, date, loader);
		for (let i = 0; i < placeholders.length; i++) {
			const { body, zone } = placeholders[i];
			if (ctx.getBody(body.data.id)) continue;
			const type = body.data.objectType;
			const parentEntry = i > 0 ? placeholders[i - 1] : null;
			// Moons whose parent is an asteroid live in the
			// `small_body_moons` zone in the regular chunk-load path. Steer
			// the placeholder there too so it's reconciled in place when the
			// real chunk arrives AND so it ends up in `bodyObjects` via the
			// asteroid-moon auto-promote — NOT in `bodiesById`, where the
			// per-frame moon `inSystem` filter (intended for major moons)
			// would freeze it whenever focus moves off the moon.
			const resolvedZone =
				type === ObjectType.MOON && parentEntry && isAsteroid(parentEntry.body.data.objectType)
					? 'small_body_moons'
					: zone;
			if (type === ObjectType.SPACECRAFT || type === ObjectType.DEBRIS) {
				const key = body.data.parentId;
				spacecraftBucket(key).set(body.data.id, body);
				placeholderById.set(body.data.id, body);
				addedSinceFlush.add(body.data.id);
				ctx.bodies.dirtySpacecraftGroups.add(key);
			} else if (resolvedZone) {
				asteroidBucket(resolvedZone).addPlaceholder(body);
				addedSinceFlush.add(body.data.id);
				ctx.bodies.dirtyAsteroidZones.add(resolvedZone);
			} else {
				// Major / undocumented / wikidata-only — no zone to route into,
				// fall back to bodiesById so getBody() still finds it.
				ctx.bodies.addBodies([body]);
			}
			ctx.credits.recordOrbitSources([body]);
		}
		if (placeholders.length > 0) flush();
	}

	// Probes ride bodiesById (so getBody / URL focus / placeholder routing
	// works) but are excluded from `majorBodies` so `buildScene` doesn't
	// build a sphere + trail for each on first paint. The hot
	// per-frame iteration loops (visibility, sphere LOD, texture LOD,
	// ring shaders) walk `bodyObjects` which only contains promoted
	// entries — keeping the long tail of probes out of that set keeps
	// the loops short. On focus, `ensureBodyObjects` builds the full
	// visual representation.
	ctx.bodies.majorBodies = major.filter(
		(b) =>
			b.data.objectType !== ObjectType.BARYCENTER &&
			b.data.objectType !== ObjectType.LAGRANGE_POINT &&
			b.data.orbitalSource !== OrbitalSource.SPICE_PROBE
	);
	ctx.loading = false;
	performance.mark('sm-majors-done');

	// Phase 2: minors — load in background, flush to reactive state periodically.
	// minorChunkArgsPromise has been running in parallel.
	const { eager: minorChunkArgs, deferred: deferredChunkArgs } = await minorChunkArgsPromise;

	// `small_body_moons` parents (asteroid hosts) live in `small_bodies/*`
	// zones, not in chebyshev — without seeding, the asteroid pass would not
	// retain their positions and the moons would skip on the parent lookup.
	// Seed first, then process parent zones, then process moons.
	const moonArgs = minorChunkArgs.filter((a) => a.zone === 'small_body_moons');
	const otherArgs = minorChunkArgs.filter((a) => a.zone !== 'small_body_moons');
	for (const arg of moonArgs) {
		await loader.seedNeededParents(arg.zone, arg.zoom, arg.part, arg.time, arg.parentIdType);
	}

	ctx.bodies.minorStreaming = true;
	const intervalId = setInterval(flush, 500);

	// Columnar ingest for the asteroid bulk (small_bodies/*): the parsed element
	// columns go straight into a MinorBucket — no per-row PositionedBody, no
	// throwaway main-thread Kepler solve. The few bodies that become objects
	// (promotion / picking / detail) materialize on demand from these columns.
	const handleColumnChunk = (zone: string, cols: ElementColumns, parentIdType: string) => {
		ctx.credits.recordOrbitSource(cols.source);
		if (cols.rowCount === 0) return;
		const added = asteroidBucket(zone).addChunk(cols, parentIdType);
		for (const id of added) addedSinceFlush.add(id);
		ctx.bodies.dirtyAsteroidZones.add(zone);
	};

	// Earth sats / debris stay on the AoS path (small count + time-segmented
	// hot-reload + group-filter machinery). Mirrors the original per-id Map
	// merge, including URL-placeholder reconciliation.
	const handleChunk = (zone: string, chunk: PositionedBody[]) => {
		ctx.credits.recordOrbitSources(chunk);
		const earthFilter = zone === 'earth' ? ctx.earthSatFilter : null;
		for (const b of chunk) {
			if (earthFilter && !earthFilter.has(b.data.id)) continue;
			const placeholder = placeholderById.get(b.data.id);
			if (placeholder) {
				placeholder.data = b.data;
				placeholder.position = b.position;
				if (b.orbitElements !== undefined) placeholder.orbitElements = b.orbitElements;
				if (b.orbitCenter !== undefined) placeholder.orbitCenter = b.orbitCenter;
				placeholderById.delete(b.data.id);
				ctx.bodies.dirtySpacecraftGroups.add(b.data.parentId);
				continue;
			}
			const key = b.data.parentId;
			const bucket = spacecraftBucket(key);
			if (!bucket.has(b.data.id)) addedSinceFlush.add(b.data.id);
			bucket.set(b.data.id, b);
			ctx.bodies.dirtySpacecraftGroups.add(key);
		}
	};

	// `small_body_moons` keep the AoS path: they're a tiny set whose positions
	// resolve against their parent asteroid (seeded above) on the main thread,
	// and the asteroid-moon auto-promote consumes the resolved bodies. Routed
	// into the bucket as loose entries so `getBody`/promotion still find them.
	const handleMoonChunk = (zone: string, chunk: PositionedBody[]) => {
		ctx.credits.recordOrbitSources(chunk);
		const bucket = asteroidBucket(zone);
		for (const b of chunk) {
			bucket.addPlaceholder(b);
			addedSinceFlush.add(b.data.id);
		}
		ctx.bodies.dirtyAsteroidZones.add(zone);
	};

	// Asteroid zones go columnar; any other elements zone (Earth sats) stays AoS.
	const asteroidOtherArgs = otherArgs.filter((a) => a.zone.startsWith('small_bodies/'));
	const spacecraftArgs = otherArgs.filter((a) => !a.zone.startsWith('small_bodies/'));

	try {
		await Promise.all([
			...asteroidOtherArgs.map(({ zone, zoom, part, time, parentIdType }) =>
				loader
					.fetchMinorColumns(zone, zoom, part, date, time, parentIdType)
					.then((cols) => handleColumnChunk(zone, cols, parentIdType))
			),
			...spacecraftArgs.map(({ zone, zoom, part, time, parentIdType }) =>
				loader
					.process(zone, zoom, part, date, time, parentIdType)
					.then((chunk) => handleChunk(zone, chunk))
			)
		]);
		// Moons last: by now their parent asteroids have populated
		// `loader.positions` via the seeded `neededParentIds` set, so
		// `process()` can resolve them instead of skipping.
		await Promise.all(
			moonArgs.map(({ zone, zoom, part, time, parentIdType }) =>
				loader
					.process(zone, zoom, part, date, time, parentIdType)
					.then((chunk) => handleMoonChunk(zone, chunk))
			)
		);
	} finally {
		clearInterval(intervalId);
		ctx.bodies.minorStreaming = false;
		flush();
		performance.mark('sm-minors-done');
		// Release the eager-minors gate (full-res skybox waits on it) even if
		// the eager wave threw — a partial point cloud shouldn't block the
		// background upgrade.
		markEagerMinorsDone();
	}

	// Deferred wave: the unnamed long tail (main-belt zoom-1 parts past the
	// eager sample). Same ingest path, started only after the eager wave so it
	// never delays the visually-representative point cloud or the majors.
	if (deferredChunkArgs.length > 0) {
		ctx.bodies.minorStreaming = true;
		const deferredInterval = setInterval(flush, 1000);
		try {
			await Promise.all(
				deferredChunkArgs.map(({ zone, zoom, part, time, parentIdType }) =>
					loader
						.fetchMinorColumns(zone, zoom, part, date, time, parentIdType)
						.then((cols) => handleColumnChunk(zone, cols, parentIdType))
				)
			);
		} finally {
			clearInterval(deferredInterval);
			ctx.bodies.minorStreaming = false;
			flush();
			performance.mark('sm-deferred-done');
		}
	}

	// Hot-reload driver: at this point metadataPromise has already
	// resolved (chebPromise awaited it), so this awaits a settled promise.
	ctx.refresher = new ZoneRefresher(ctx, await metadataPromise, loader, date);
}
