import { ObjectType, type PositionedBody } from '$lib/types/objects';
import { ChunkLoader } from '$lib/fetch/position/chunk';
import { fetchLabels } from '$lib/fetch/position/labels';
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
import { createPlaceholderBody } from '$lib/scene/setup/placeholder';
import type { ContextManager } from '$lib/scene/state/context-manager.svelte';

interface MinorChunkArg {
	zone: string;
	zoom: number;
	part: number;
	time: string | null;
	parentIdType: string;
}

/**
 * Walk every minor zone in metadata and produce the chunk-fetch plan for
 * phase 2. Also fires `ChunkLoader.prefetch` for each entry so the HTTP cache
 * is warm by the time phase 2 awaits its `loader.process` call.
 *
 * Skipped zones:
 *  - `major` / `moons`: phase 1 territory.
 *  - `spacecraft`: legacy Sun-orbiter Kepler-fallback zone, now shipped via probes.
 *  - Probe zones: loaded through ProbeStore, not ChunkLoader.
 *  - Chebyshev zones (`shape: chunked`): loaded through ChebyshevStore.
 */
function planMinorChunks(metadata: Metadata, date: Date): MinorChunkArg[] {
	const args: MinorChunkArg[] = [];
	for (const [zone, zoneData] of Object.entries(metadata.position.zones)) {
		if (zone === 'major' || zone === 'moons') continue;
		if (zone === 'spacecraft') continue;
		if (isProbeZone(zoneData)) continue;
		const parentIdType = zoneData.parent_id_type ?? 'naif';
		for (const [zoomStr, zoomData] of Object.entries(zoneData.zooms)) {
			const zoom = Number(zoomStr);
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
}

/**
 * Build the probe ephemeris store from metadata, or return null when the
 * export ships no probe zones. Logs zone counts on success and warns about
 * any zones missing a `fit_center_naif_id` (a re-export will refresh the
 * field).
 */
async function buildProbeStore(metadata: Metadata, jd: number): Promise<ProbeStore | null> {
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
 * Phase 1 majors. Bodies arrive from four sources, in dependency order:
 *  - Chebyshev (`loader.processChebyshev`): Sun, planets/dwarves with SPK
 *    kernels, perturber asteroids, whitelisted moons. Runs first so its
 *    barycenters/Sun land in `loader.positions` before kepler-fallback
 *    dwarves (which parent on those barycenters) try to resolve.
 *  - `major/1` elements: horizons-sourced majors not in chebyshev — in
 *    practice this catches dwarf planets with Horizons ephemerides but no
 *    SPK kernel.
 *  - `major/2` elements: SBDB-only dwarves (Eris, Makemake, Quaoar, …) that
 *    aren't in any SPK kernel either.
 *  - `moons` elements: non-whitelisted moons (Method-C secular elements,
 *    chunk-indexed).
 *
 * Zoom 0 is reserved for chebyshev — kepler fallbacks live at higher zooms
 * so the per-zoom shape stays single-payload.
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
	const loader = new ChunkLoader(ctx.chebStore);

	const major = await loadMajorBodies(ctx, loader, metadata, date, jd);
	ctx.bodies.addBodies(major);
	ctx.credits.recordOrbitSources(major);

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
		ctx.bodies.asteroidBodiesByZone = cloneOuter(pendingAsteroids);
		ctx.bodies.spacecraftByParent = cloneOuter(pendingSpacecraft);
		ctx.bodies.minorBodyVersion++;
	};

	// If the target body wasn't in majors/moons, resolve it from the global
	// object file and route it into the same per-zone store its chunk will
	// land in — keeps a single source of truth and lets phase 2 reconcile
	// in place when the chunk arrives.
	if (targetId && !ctx.getBody(targetId)) {
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
				ctx.bodies.dirtySpacecraftGroups.add(key);
			} else if (zone) {
				let bucket = pendingAsteroids.get(zone);
				if (!bucket) pendingAsteroids.set(zone, (bucket = new Map()));
				bucket.set(body.data.id, body);
				placeholderById.set(body.data.id, body);
				ctx.bodies.dirtyAsteroidZones.add(zone);
			} else {
				// Major / undocumented / wikidata-only — no zone to route into,
				// fall back to bodiesById so getBody() still finds it.
				ctx.bodies.addBodies([body]);
			}
			ctx.credits.recordOrbitSources([body]);
			flush();
		}
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

	// Phase 2: minors — load in background, flush to reactive state periodically.
	// minorChunkArgsPromise has been running in parallel; files are likely cached already.
	const minorChunkArgs = await minorChunkArgsPromise;

	const intervalId = setInterval(flush, 500);

	try {
		await Promise.all(
			minorChunkArgs.map(({ zone, zoom, part, time, parentIdType }) =>
				loader.process(zone, zoom, part, date, time, parentIdType).then((chunk) => {
					ctx.credits.recordOrbitSources(chunk);
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
							// focused sat's trail tracking parent motion.
							if (b.orbitElements !== undefined) placeholder.orbitElements = b.orbitElements;
							if (b.orbitCenter !== undefined) placeholder.orbitCenter = b.orbitCenter;
							placeholderById.delete(b.data.id);
							if (b.data.objectType === ObjectType.SPACECRAFT) {
								ctx.bodies.dirtySpacecraftGroups.add(b.data.parentId);
							} else {
								ctx.bodies.dirtyAsteroidZones.add(zone);
							}
							continue;
						}
						if (b.data.objectType === ObjectType.SPACECRAFT) {
							let bucket = pendingSpacecraft.get(b.data.parentId);
							if (!bucket) pendingSpacecraft.set(b.data.parentId, (bucket = new Map()));
							bucket.set(b.data.id, b);
							ctx.bodies.dirtySpacecraftGroups.add(b.data.parentId);
						} else {
							let bucket = pendingAsteroids.get(zone);
							if (!bucket) pendingAsteroids.set(zone, (bucket = new Map()));
							bucket.set(b.data.id, b);
							ctx.bodies.dirtyAsteroidZones.add(zone);
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
	ctx.refresher = new ZoneRefresher(ctx, await metadataPromise, loader, date);
}
