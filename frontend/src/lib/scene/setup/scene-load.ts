import { ObjectType, isAsteroid, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/position/chunk';
import { fetchLabels } from '$lib/fetch/position/labels';
import { MinorBucket } from '$lib/fetch/position/minor-columns';
import type { ElementColumns } from '$lib/fetch/position/elements/parse';
import { OrbitalSource } from '$lib/fetch/position/format';
import { loadAtmospheres } from '$lib/fetch/atmospheres';
import { loadSystemsGlobal } from '$lib/fetch/systems-global';
import {
	chebyshevZoneParams,
	chunkIndexForJd,
	fetchMetadata,
	flatZoom,
	isChunkIndexed,
	isDateSegmented,
	isParted,
	isProbeZone,
	isZoomedZone,
	partsForDate,
	probeZoneParams,
	snapshotDate,
	zoneLayers,
	type Metadata
} from '$lib/fetch/metadata';
import { dateToJD } from '$lib/format/date';
import { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { ProbeStore } from '$lib/fetch/position/probes/store';
import { ZoneRefresher } from '$lib/scene/zone-refresher';
import { prefetchSkyboxTiers } from '$lib/scene/objects/sky/skybox';
import { markEagerMinorsDone } from '$lib/scene/setup/load-gates';
import { isLowEndDevice } from '$lib/device';
import { createPlaceholderBody } from '$lib/scene/setup/placeholder';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';
import { getSettings } from '$lib/state/settings.svelte';
import { loadProgress } from '$lib/scene/state/load-progress.svelte';

interface MinorChunkArg {
	zone: string;
	zoom: number | null;
	part: number;
	time: string | null;
	parentIdType: string;
}

/**
 * Parts are hash-bucketed shards, so the first N parts of a zoom bucket are a
 * representative sample. Unnamed (zoom-1) parts past this cap defer until the
 * eager wave finishes, so density lands before the long tail competes for
 * bandwidth. Only the main belt (133 zoom-1 parts) exceeds this today.
 */
const EAGER_ZOOM1_PARTS = 13;

/**
 * Phase-2 chunk-fetch plan: eager wave (named + a representative sample of
 * unnamed) plus a deferred wave (the unnamed long tail). No prefetch warming
 * — firing every part up front would starve the phase-1 critical path on
 * bandwidth-bound links. Skips `major`/`moons` (phase 1), probe zones, chebyshev.
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
		for (const { zoom, data: zoomData } of zoneLayers(zoneData)) {
			if (zoomData.shape === 'chunked') continue;
			// Date-segmented zones (earth): pick snapshot nearest the sim time so SGP4's window covers it.
			const time = isDateSegmented(zoomData) ? snapshotDate(zoomData, date) : null;
			const limit =
				isDateSegmented(zoomData) && time !== null
					? partsForDate(zoomData, time, cap)
					: cap > 0
						? Math.min(zoomData.parts, cap)
						: zoomData.parts;
			for (let part = 0; part < limit; part++) {
				const arg = { zone, zoom, part, time, parentIdType };
				if (zoom !== null && zoom >= 1 && part >= EAGER_ZOOM1_PARTS) deferred.push(arg);
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
 * Phase 1 majors, in dependency order: chebyshev first (Sun/planets/perturbers/
 * whitelisted moons) so `loader.positions` is populated before kepler-fallback
 * dwarves resolve their parents; then `major/1`, `major/2`, `moons`.
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
	if (majorZone && isZoomedZone(majorZone)) {
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
	const moonsZoom = moonsZone ? flatZoom(moonsZone) : undefined;
	const moonsTime =
		moonsZoom && isChunkIndexed(moonsZoom) ? String(chunkIndexForJd(moonsZoom, jd)) : null;
	if (moonsZoom) {
		major.push(...(await loader.process('moons', null, 0, date, moonsTime)));
	}
	return major;
}

/**
 * Boot the scene's data layer, two-phase so first paint lands before tens of
 * thousands of asteroids do. Phase 1 (awaited): ephemeris stores + major/moon
 * chunks — once in `bodies.majorBodies`, the renderer can build the scene, and
 * `loading` flips false. Phase 2 (background): minor-body chunks, flushed into
 * `ctx.bodies` every 500ms so point clouds grow while the page stays interactive.
 *
 * Caller resets `loading` on a thrown error — this only clears it on success.
 */
export async function loadScene(ctx: ContextManager, date: Date, targetId?: string): Promise<void> {
	// IAU nutation/precession angles + per-body GMs. Fire-and-forget; rotation
	// falls back to the first-order model until it lands.
	performance.mark('sm-load-start');
	loadProgress.reset();
	void loadSystemsGlobal().catch((e) =>
		console.warn('scene-load: systems-global (GMs/nutation) failed to load:', e)
	);
	// Awaited before majors land — scattering shells build synchronously with
	// each body mesh, so params must already be in the registry.
	const atmospheresPromise = loadAtmospheres().catch((e) =>
		console.warn('scene-load: atmospheres failed to load — rendering without shells:', e)
	);
	const jd = dateToJD(date);
	const metadataPromise = fetchMetadata();

	// ZoneRefresher owns chunk-indexed moons prefetch; the flat-zone case (no
	// chunk index) is handled here as a one-shot HTTP warm.
	metadataPromise.then((metadata) => {
		const moons = metadata.position.zones.moons;
		if (!moons) return;
		const moonsZoom = flatZoom(moons);
		if (moonsZoom && isParted(moonsZoom)) {
			ChunkLoader.prefetch('moons', null, 0, null);
		}
	});

	// Start fetching+decoding the skybox low tier as soon as the tier list is
	// known, rather than waiting for renderer init.
	metadataPromise.then((metadata) => {
		if (metadata.skybox) prefetchSkyboxTiers(metadata.skybox);
	});

	const minorChunkArgsPromise = metadataPromise.then((metadata) => planMinorChunks(metadata, date));

	// Chebyshev must be ready before major/moons — it supplies the only
	// positions for the bodies it covers, no fallback. Probes lag chebyshev
	// too: fit-center positions must be in `loader.positions` first.
	const chebPromise = metadataPromise.then(async (metadata) => {
		const params = chebyshevZoneParams(metadata);
		if (params.size === 0) return null;
		const store = new ChebyshevStore(params);
		await store.ensure(jd).done;
		return store;
	});
	const probePromise = metadataPromise.then((metadata) => buildProbeStore(metadata, jd));

	const metadata = await metadataPromise;
	loadProgress.reach('metadata');
	ctx.chebStore = await chebPromise;
	ctx.probeStore = await probePromise;
	loadProgress.reach('ephemeris');
	const loader = new ChunkLoader(ctx.chebStore);

	const major = await loadMajorBodies(ctx, loader, metadata, date, jd);
	loadProgress.reach('majors');
	await atmospheresPromise;
	ctx.bodies.addBodies(major);
	ctx.credits.recordOrbitSources(major);

	// Awaited once so each MinorBucket can materialize names/flags on demand
	// without re-awaiting per chunk.
	const labels = await fetchLabels();
	loadProgress.reach('labels');

	// Chunks add in place; the outer Map is re-wrapped on flush for reactivity.
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

	// URL-loaded spacecraft placeholders: mutated in place when the real chunk
	// lands so the renderer's held BodyObject ref stays valid.
	const placeholderById = new Map<string, PositionedBody>();
	// Ids added since the last flush, drained into `notifyBodiesAdded` so the
	// promotion registry picks up new bodies without polling.
	const addedSinceFlush = new Set<string>();

	const flush = () => {
		// Re-wrap for reactivity — inner MinorBucket refs stay stable.
		ctx.bodies.asteroidBodiesByZone = new Map(ctx.bodies.asteroidBodiesByZone);
		ctx.bodies.spacecraftByParent = new Map(ctx.bodies.spacecraftByParent);
		ctx.bodies.minorBodyVersion++;
		if (addedSinceFlush.size > 0) {
			ctx.bodies.notifyBodiesAdded([...addedSinceFlush]);
			addedSinceFlush.clear();
		}
	};

	// If the target wasn't in majors/moons, route it into the same per-zone
	// store its real chunk will land in, so phase 2 reconciles it in place.
	if (targetId && !ctx.getBody(targetId)) {
		// Ancestor placeholders (target's parent not yet in `loader.positions`)
		// get the same routing pass so they show up immediately too.
		const placeholders = await createPlaceholderBody(targetId, date, loader);
		for (let i = 0; i < placeholders.length; i++) {
			const { body, zone } = placeholders[i];
			if (ctx.getBody(body.data.id)) continue;
			const type = body.data.objectType;
			const parentEntry = i > 0 ? placeholders[i - 1] : null;
			// Asteroid-moon placeholders steer into `small_body_moons` so they
			// reconcile via the auto-promote path into `bodyObjects` — not
			// `bodiesById`, where the moon `inSystem` filter would freeze them
			// once focus moves off.
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

	// Probes ride bodiesById (for getBody/URL-focus/routing) but stay out of
	// `majorBodies` so `buildScene` skips a sphere+trail per probe, and out of
	// `bodyObjects` (hot per-frame loops) until `ensureBodyObjects` builds
	// them on focus.
	ctx.bodies.majorBodies = major.filter(
		(b) =>
			b.data.objectType !== ObjectType.BARYCENTER &&
			b.data.objectType !== ObjectType.LAGRANGE_POINT &&
			b.data.orbitalSource !== OrbitalSource.SPICE_PROBE
	);
	loadProgress.reach('done');
	ctx.loading = false;
	performance.mark('sm-majors-done');

	// Phase 2: minors, loaded in background, flushed to reactive state periodically.
	const { eager: minorChunkArgs, deferred: deferredChunkArgs } = await minorChunkArgsPromise;

	// `small_body_moons` parents (asteroid hosts) live in `small_bodies/*`, not
	// chebyshev — seed their positions first, or the moons skip on parent lookup.
	const moonArgs = minorChunkArgs.filter((a) => a.zone === 'small_body_moons');
	const otherArgs = minorChunkArgs.filter((a) => a.zone !== 'small_body_moons');
	// Phase 1 already rendered, so a seed failure costs only the moons it
	// feeds, not the whole scene.
	for (const arg of moonArgs) {
		try {
			await loader.seedNeededParents(arg.zone, arg.zoom, arg.part, arg.time, arg.parentIdType);
		} catch (e) {
			console.warn(`scene-load: seedNeededParents failed for ${arg.zone} part ${arg.part}:`, e);
		}
	}

	ctx.bodies.minorStreaming = true;
	const intervalId = setInterval(flush, 500);

	// Columnar ingest for the asteroid bulk: parsed columns go straight into a
	// MinorBucket, no per-row PositionedBody or throwaway Kepler solve. Bodies
	// that get promoted materialize on demand from these columns.
	const handleColumnChunk = (zone: string, cols: ElementColumns, parentIdType: string) => {
		ctx.credits.recordOrbitSource(cols.source);
		if (cols.rowCount === 0) return;
		const added = asteroidBucket(zone).addChunk(cols, parentIdType);
		for (const id of added) addedSinceFlush.add(id);
		ctx.bodies.dirtyAsteroidZones.add(zone);
	};

	// Earth sats/debris stay on the AoS path (small count, time-segmented
	// hot-reload, group filters), with URL-placeholder reconciliation.
	const handleChunk = (zone: string, chunk: PositionedBody[]) => {
		ctx.credits.recordOrbitSources(chunk);
		const isEarth = zone === 'earth';
		const earthFilter = isEarth ? ctx.earthSatFilter : null;
		const typeFilter = isEarth ? ctx.earthTypeFilter : null;
		for (const b of chunk) {
			if (earthFilter && !earthFilter.has(b.data.id)) continue;
			if (typeFilter && !typeFilter.has(b.data.objectType)) continue;
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

	// `small_body_moons` keep the AoS path: a tiny set resolved against their
	// seeded parent asteroid, routed as loose bucket entries so
	// `getBody`/promotion still find them.
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

	// Per-chunk catch so one flaky part doesn't reject the wave and kill
	// hot-reload for the session; record the zone so the refresher retries it.
	const failedZones = new Set<string>();
	const onChunkFail = (zone: string, part: number) => (e: unknown) => {
		failedZones.add(zone);
		console.warn(`scene-load: ${zone} part ${part} failed (skipped):`, e);
	};

	try {
		await Promise.all([
			...asteroidOtherArgs.map(({ zone, zoom, part, time, parentIdType }) =>
				loader
					.fetchMinorColumns(zone, zoom, part, date, time, parentIdType)
					.then((cols) => handleColumnChunk(zone, cols, parentIdType))
					.catch(onChunkFail(zone, part))
			),
			...spacecraftArgs.map(({ zone, zoom, part, time, parentIdType }) =>
				loader
					.process(zone, zoom, part, date, time, parentIdType)
					.then((chunk) => handleChunk(zone, chunk))
					.catch(onChunkFail(zone, part))
			)
		]);
		// Moons last: their parent asteroids have populated `loader.positions`
		// by now, via the seed above, so `process()` can resolve them.
		await Promise.all(
			moonArgs.map(({ zone, zoom, part, time, parentIdType }) =>
				loader
					.process(zone, zoom, part, date, time, parentIdType)
					.then((chunk) => handleMoonChunk(zone, chunk))
					.catch(onChunkFail(zone, part))
			)
		);
	} finally {
		clearInterval(intervalId);
		ctx.bodies.minorStreaming = false;
		flush();
		performance.mark('sm-minors-done');
		// Release the eager-minors gate (full-res skybox waits on it) even on
		// a thrown wave — a partial point cloud shouldn't block the upgrade.
		markEagerMinorsDone();
	}

	// Deferred wave: the unnamed main-belt long tail (~120 parts, 100 MB+ of
	// typed arrays), started after the eager wave so it never delays the
	// representative point cloud. Skipped on memory-constrained clients — it's
	// the single largest OOM contributor and purely additive density.
	if (deferredChunkArgs.length > 0 && isLowEndDevice()) {
		console.info(
			`Low-end device: skipping ${deferredChunkArgs.length} deferred minor-belt parts to conserve memory`
		);
	} else if (deferredChunkArgs.length > 0) {
		ctx.bodies.minorStreaming = true;
		const deferredInterval = setInterval(flush, 1000);
		try {
			await Promise.all(
				deferredChunkArgs.map(({ zone, zoom, part, time, parentIdType }) =>
					loader
						.fetchMinorColumns(zone, zoom, part, date, time, parentIdType)
						.then((cols) => handleColumnChunk(zone, cols, parentIdType))
						.catch(onChunkFail(zone, part))
				)
			);
		} finally {
			clearInterval(deferredInterval);
			ctx.bodies.minorStreaming = false;
			flush();
			performance.mark('sm-deferred-done');
		}
	}

	// Guarded so a construction hiccup leaves the live scene intact (hot-reload
	// stays off) instead of rejecting into the error screen.
	try {
		ctx.refresher = new ZoneRefresher(ctx, await metadataPromise, loader, date);
		// A failed boot part left its snapshot partial — re-fire the zone to
		// recover, since the refresher won't reload until a rollover.
		for (const zone of failedZones) ctx.refresher.invalidateZone(zone);
	} catch (e) {
		console.error('scene-load: ZoneRefresher init failed; hot-reload disabled:', e);
	}
}
