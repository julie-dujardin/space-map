import { fetchLabels, type LabelMap } from '$lib/fetch/position/labels';
import { fetchWithTimeout } from '$lib/fetch/fetch-timeout';
import {
	type KeplerianColumns,
	type ParabolicColumns,
	type SGP4Columns,
	type ElementColumns
} from '$lib/fetch/position/elements/parse';
import {
	pickLabel,
	pickIsMinor,
	keplerianToBody,
	parabolicToBody,
	sgp4ToBody
} from '$lib/fetch/position/elements/row';
import { LruPromiseCache } from '$lib/fetch/position/cache';
import { isMajorBody } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { yieldToMain } from '$lib/yield';
import { OrbitalSource, chunkedPartedUrl, partedUrl } from '$lib/fetch/position/format';
import { parsePosition } from '$lib/fetch/position/parse';
import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types/objects';
import { AU_KM, AU_SCALE, KM3_S2_TO_AU3_DAY2, KM_DAY_TO_AU_DAY } from '$lib/math/units';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { chebyshevPositionScene, chebyshevStateKm } from '$lib/fetch/position/chebyshev/propagate';
import type { ChebyshevBody } from '$lib/fetch/position/chebyshev/parse';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import { probeOsculatingElements } from '$lib/fetch/position/probes/elements';
import { resolveProbePrimary } from '$lib/fetch/position/probes/primary';
import { deriveProbeTrailParams } from '$lib/fetch/position/probes/trail';
import { stateVectorToElements } from '$lib/math/orbit/state';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import { NUM_TRAIL_POINTS } from '$lib/scene/objects/trail/points';
import { dateToJD } from '$lib/time/jd';

/** NAIF ids of the two heliocentric origins, as the binary carries them. */
const SSB_NAIF_ID = 0;
const SUN_NAIF_ID = 10;

/**
 * Osculating Keplerian elements from a chebyshev body's state at `jd`, with
 * the parent's GM. Null when the parent has no GM, the sample misses, or the
 * state degenerates. Drives the trail curve through the same kepler path as
 * SBDB-sourced bodies (see `processChebyshev`); re-invoked periodically via
 * `PositionedBody.rederiveElements` to keep the ellipse aligned as time advances.
 */
function chebyshevOsculatingElements(
	body: ChebyshevBody,
	parentId: number,
	jd: number,
	origin?: ChebyshevBody
): OrbitalElements | null {
	const gmKm3s2 = getGmKm3s2(parentId);
	if (!gmKm3s2) return null;
	const state = chebyshevStateKm(body, jd);
	if (!state) return null;
	const from = origin ? chebyshevStateKm(origin, jd) : null;
	if (origin && !from) return null;
	const muAuDay2 = gmKm3s2 * KM3_S2_TO_AU3_DAY2;
	const r: [number, number, number] = [
		(state.position[0] - (from?.position[0] ?? 0)) / AU_KM,
		(state.position[1] - (from?.position[1] ?? 0)) / AU_KM,
		(state.position[2] - (from?.position[2] ?? 0)) / AU_KM
	];
	const v: [number, number, number] = [
		(state.velocity[0] - (from?.velocity[0] ?? 0)) * KM_DAY_TO_AU_DAY,
		(state.velocity[1] - (from?.velocity[1] ?? 0)) * KM_DAY_TO_AU_DAY,
		(state.velocity[2] - (from?.velocity[2] ?? 0)) * KM_DAY_TO_AU_DAY
	];
	return stateVectorToElements(r, v, muAuDay2, jd);
}

/**
 * The Sun-centred orbit of a body the ephemeris places against the barycentre.
 * The SSB-relative fit isn't a real orbit — nothing goes round the barycentre,
 * and it absorbs the Sun's wobble into the semi-major axis (Venus comes out
 * 1.5% wide), walking a propagated position tens of millions of km off over a
 * few years. Fine for a redrawn ellipse, ruinous for the trajectory planner —
 * so heliocentric bodies get a second fit against the Sun's GM instead.
 */
function chebyshevHelioElements(
	body: ChebyshevBody,
	jd: number,
	sun: ChebyshevBody | null
): OrbitalElements | null {
	if (!sun || body.parentId !== SSB_NAIF_ID || body.naifId === SUN_NAIF_ID) return null;
	return chebyshevOsculatingElements(body, SUN_NAIF_ID, jd, sun);
}

/** Build the URL for an elements-payload position file. Static parted zones
 *  skip the time component; chunked-parted zones inject it as a path segment.
 *  Chebyshev zones use `ChebyshevStore`'s own builder instead. */
function elementsUrl(zone: string, zoom: number | null, part: number, time: string | null): string {
	return time ? chunkedPartedUrl(zone, zoom, time, part) : partedUrl(zone, zoom, part);
}

/** Sized to hold the Earth-sat hot-reload window plus a few other zones the
 *  user might bounce between. Each entry retains ~5–10 MB (Earth's ~25K rows). */
const PARSED_ELEMENTS_CACHE_CAPACITY = 8;
const elementsCache = new LruPromiseCache<ElementColumns>(PARSED_ELEMENTS_CACHE_CAPACITY);

/** One elements file, parsed. */
export async function fetchElements(
	zone: string,
	zoom: number | null,
	part: number,
	time: string | null,
	priority?: RequestPriority
): Promise<ElementColumns> {
	const key = `${zone}:${zoom ?? ''}:${part}:${time ?? ''}`;
	return elementsCache.getOrCompute(key, async () => {
		const res = await fetchWithTimeout(elementsUrl(zone, zoom, part, time), { priority });
		if (!res.ok) throw new Error(`Failed to fetch elements: ${res.status}`);
		const ds = new DecompressionStream('gzip');
		const buffer = await new Response(res.body!.pipeThrough(ds)).arrayBuffer();
		const parsed = parsePosition(buffer);
		if (parsed.kind !== 'elements') {
			throw new Error(`Expected elements payload at ${zone}/${zoom}/${part}, got ${parsed.kind}`);
		}
		return parsed.columns;
	});
}

export class ChunkLoader {
	/**
	 * Fire-and-forget fetch of the position file for a zone/zoom/part so the
	 * browser caches it before the caller needs to process it. IDs ride inside
	 * the binary (header id-type byte + column 0). Labels live in one global
	 * file per language, prefetched once on app start by {@link fetchLabels}.
	 */
	static prefetch(
		zone: string,
		zoom: number | null,
		part: number,
		time: string | null = null
	): void {
		fetch(elementsUrl(zone, zoom, part, time));
	}

	/** Barycenter elements used for planet orbit drawing. `processChebyshev`
	 *  populates first (so `process` sees them when resolving planet parents). */
	barycenters = new Map<string, OrbitalElements>();
	/**
	 * Past-position ring buffers for probes with at least one chebyshev
	 * sub-chunk. Keyed by probe.id, tagged with the current parent key so a
	 * zone crossing (parent flip) clears stale OLD-frame entries. Owned here
	 * so trail history survives chunk-load passes.
	 */
	private readonly probeBuffers = new Map<string, { buffer: TrailBuffer; parentKey: string }>();

	constructor(private readonly cheb: ChebyshevStore | null) {}

	/**
	 * Build PositionedBody[] for every chebyshev body covered by `date`. Caller
	 * must `await store.ensure(jd).done` first. Walks barycenter-first so a
	 * planet finds the elements of its barycenter; each body carries osculating
	 * Keplerian elements matching the SBDB/Horizons shape for the unified
	 * kepler trail curve. The placement pass gives the bodies their places.
	 */
	processChebyshev(date: Date, labels: LabelMap): PositionedBody[] {
		if (!this.cheb) return [];
		const jd = dateToJD(date);
		const firstPass = this.barycenters.size === 0;
		const result: PositionedBody[] = [];
		// Look up chebyshev body by NAIF so borrowed bodies (planets) can attach
		// a rederive callback that points at the *parent's* chebyshev — the
		// barycenter whose orbit the planet visually shares.
		const chebBodiesByNaif = new Map<number, ChebyshevBody>();

		// Order bodies so parents resolve before children. Barycenters
		// (object_type=0) and stars (object_type=2) come first, then planets
		// (object_type=3) and dwarves (4), then moons (5+). Within a tier,
		// stable by naif_id so the major bodies appear in a deterministic order.
		const all = Array.from(this.cheb.bodiesAt(jd));
		all.sort((a, b) => {
			// Barycentres, the Sun, planets, then the rest: a moon's elements are
			// taken about its planet, so the planet's position has to exist first.
			const tier = (body: ChebyshevBody) =>
				body.objectType === ObjectType.BARYCENTER
					? 0
					: body.objectType === ObjectType.STAR
						? 1
						: body.naifId % 100 === 99
							? 2
							: 3;
			return tier(a.body) - tier(b.body) || a.body.naifId - b.body.naifId;
		});

		const cheb = this.cheb;
		const sun = cheb.body(`naif-${SUN_NAIF_ID}`, jd);
		for (const { body, startJd, endJd } of all) {
			const offset = chebyshevPositionScene(body, jd);
			if (!offset) continue;
			chebBodiesByNaif.set(body.naifId, body);
			const parentKey = `naif-${body.parentId}`;
			const objType = body.objectType as ObjectType;
			// A moon's elements are about its planet, not the system barycentre
			// the ephemeris centres it on. The two differ by 4,700 km for the
			// Moon, which read as a 25-day period and a 362,000 km semi-major
			// axis; the barycentre's GM is still the right μ (planet plus moon).
			const primaryId =
				objType === ObjectType.MOON && body.parentId >= 1 && body.parentId <= 9
					? `naif-${body.parentId * 100 + 99}`
					: null;
			// Elements about the primary when there is one. Null when the primary has no
			// record: elements about the barycentre do not agree with a curve on the primary.
			const elementsAt = (record: ChebyshevBody, at: number): OrbitalElements | null => {
				if (!primaryId) return chebyshevOsculatingElements(record, record.parentId, at);
				const primary = cheb.body(primaryId, at);
				return primary ? chebyshevOsculatingElements(record, record.parentId, at, primary) : null;
			};
			// Null elements: the body has a place, and no curve.
			const elements = elementsAt(body, jd);
			// The records are per chunk: read the one that covers the date by id.
			const ownId = body.id;
			const ownRederive = (newJd: number): OrbitalElements | null => {
				const fresh = cheb.body(ownId, newJd);
				return fresh ? elementsAt(fresh, newJd) : null;
			};
			// Position-magnitude proxy for visibility-ratio code when elements
			// are unavailable. Cheb gives parent-relative offsets in scene units,
			// so dividing by AU_SCALE recovers AU magnitude. Otherwise prefer
			// the derived |a| so high-e snapshots don't read as small-orbit.
			const fallbackA = Math.hypot(offset[0], offset[1], offset[2]) / AU_SCALE;
			const data: BodyData = {
				id: body.id,
				name: pickLabel(labels, body.id),
				isMinor: pickIsMinor(labels, body.id),
				hasLocalized: body.hasLocalized,
				objectType: objType,
				parentId: `naif-${body.parentId}`,
				radiusKm: body.radiusKm,
				a: elements ? Math.abs(elements.a) : fallbackA,
				e: elements?.e ?? 0,
				i: elements?.i ?? 0,
				om: elements?.om ?? 0,
				w: elements?.w ?? 0,
				ma: elements?.ma ?? 0,
				n: elements?.n ?? 0,
				epoch: elements?.epoch ?? 0,
				equatorial: false,
				helioElements: chebyshevHelioElements(body, jd, sun) ?? undefined,
				validityStart: startJd,
				validityEnd: endJd,
				orbitalSource: OrbitalSource.SPICE,
				visibleFromDays: body.visibleFromDays
			};
			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				if (firstPass && elements && elements.a > 0 && elements.e < 1) {
					this.barycenters.set(body.id, elements);
				}
				result.push({
					data,
					position: null,
					orbitElements: elements ?? undefined,
					orbitCenterId: parentKey,
					rederiveElements: ownRederive
				});
				continue;
			}
			if (isMajorBody(objType)) {
				// Mirror the elements path: planets use the parent barycenter's
				// orbit (the planet's own offset is just wobble); moons use
				// their own. A borrowed curve has no centre body: it is drawn
				// about the barycentre of the Solar System.
				const isMoon = objType === ObjectType.MOON;
				const parentElements = this.barycenters.get(parentKey);
				const orbitElements = isMoon ? elements : (parentElements ?? elements);
				const borrowedFromParent = !isMoon && parentElements !== undefined;
				// Borrowed bodies must re-derive against the *parent's* chebyshev,
				// since `orbitElements` traces the parent barycenter's orbit, not
				// the planet's wobble. Capture the parent's stable string id (not
				// the per-chunk body record — see `ownRederive` above) so the
				// callback resolves the live record each call.
				const parentChebId = chebBodiesByNaif.get(body.parentId)?.id;
				const rederiveElements =
					borrowedFromParent && parentChebId
						? (newJd: number): OrbitalElements | null => {
								const fresh = cheb.body(parentChebId, newJd);
								if (!fresh) return null;
								return chebyshevOsculatingElements(fresh, fresh.parentId, newJd);
							}
						: ownRederive;
				result.push({
					data,
					position: null,
					orbitElements: orbitElements ?? undefined,
					// A moon's curve sits on its planet, where its elements are taken.
					orbitCenterId: borrowedFromParent ? undefined : (primaryId ?? parentKey),
					// The borrowed curve traces the orbit of the barycenter, so the
					// bright end of the trail belongs on the barycenter.
					trailAnchorId: borrowedFromParent ? parentKey : undefined,
					rederiveElements
				});
			} else {
				result.push({
					data,
					position: null,
					orbitElements: elements ?? undefined,
					orbitCenterId: parentKey,
					rederiveElements: ownRederive
				});
			}
		}
		return result;
	}

	/**
	 * Build PositionedBody[] for every probe whose current chunk is resident in
	 * `probeStore`. Mirrors `processChebyshev`: resolves each probe's fit-center
	 * body and its GM, needed to evaluate Kepler-pure sub-chunks. The placement
	 * pass gives the probes their places.
	 *
	 * Trail handling splits per probe: pure-Kepler probes carry an osculating
	 * snapshot (`orbitElements` + `rederiveElements`) that `refreshTrail`
	 * re-snapshots across sub-chunk boundaries. A probe with any chebyshev
	 * sub-chunk instead gets a `TrailBuffer` of past positions — an osculating
	 * ellipse misrepresents a flyby/capture/depart maneuver, so the real path
	 * is polylined instead.
	 *
	 * `validityStart/End` come from the chunk's header bounds, so the renderer
	 * can hide a probe whose chunk isn't loaded rather than render stale data.
	 */
	processProbes(probeStore: ProbeStore, date: Date, labels: LabelMap): PositionedBody[] {
		const jd = dateToJD(date);
		const result: PositionedBody[] = [];
		const missingGm = new Map<string, Set<string>>(); // "naif-<id>" or "naif-undefined" → probe ids
		const undefinedCenterProbes = new Set<string>();
		// At boot there's no focused system, so the initial zone wins by metadata
		// order (interplanetary first); the per-frame propagator flips parentId later.
		// `id` is the probe's own, except for a craft riding another: the record
		// is then the carrier's, and everything identity-keyed below — label,
		// trail buffer, re-derive — belongs to the passenger.
		for (const { id, probe, zoneCenterNaifId, startJd, endJd } of probeStore.probesAt(jd)) {
			if (!id) continue;
			if (zoneCenterNaifId === undefined) undefinedCenterProbes.add(id);
			const zoneCenterKey = `naif-${zoneCenterNaifId}`;
			// Sub-chunks are fit against the probe's actual fit center: the stamped
			// override (Moon for lunar orbiters, Ryugu for Hayabusa2, …) or the zone
			// center. Only its identity and GM are needed here. The placement pass
			// resolves it again at each date and hides the probe when it has no place.
			const primary =
				zoneCenterNaifId === undefined
					? null
					: resolveProbePrimary(probe, jd, zoneCenterNaifId, this.cheb, () => true);
			const primaryKey = primary ? primary.id : zoneCenterKey;
			const primaryMu = primary?.muKm3S2 ?? 0;
			if (primaryMu === 0) {
				let s = missingGm.get(primaryKey);
				if (!s) missingGm.set(primaryKey, (s = new Set()));
				s.add(id);
			}
			const data: BodyData = {
				id,
				name: pickLabel(labels, id),
				isMinor: pickIsMinor(labels, id),
				hasLocalized: probe.hasLocalized,
				objectType: probe.objectType as ObjectType,
				parentId: primaryKey,
				loadParentId: primaryKey,
				radiusKm: NaN, // probes have no physical-radius column; renderer falls back
				a: 0,
				e: 0,
				i: 0,
				om: 0,
				w: 0,
				ma: 0,
				n: 0,
				epoch: 0,
				equatorial: false,
				validityStart: startJd,
				validityEnd: endJd,
				orbitalSource: OrbitalSource.SPICE_PROBE
			};
			const elements = probeOsculatingElements(probe, jd, primaryMu);
			// Re-read the probe and its fit center on every call: scrubbing can move
			// it to another chunk (stale Probe ref) or zone (cruise → captured
			// orbit), and a late GM table self-heals on the next re-derive.
			const ownId = id;
			const cheb = this.cheb;
			const rederiveElements = (newJd: number): OrbitalElements | null => {
				const located = probeStore.probeWithCenter(ownId, newJd);
				if (!located) return null;
				const fresh = resolveProbePrimary(
					located.probe,
					newJd,
					located.fitCenterNaifId,
					cheb,
					() =>
						// Elements only need mu, not a live position — a stamped small
						// body resolves by identity here.
						true
				);
				if (!fresh) return null;
				return probeOsculatingElements(located.probe, newJd, fresh.muKm3S2);
			};
			// Every probe polylines its real past positions rather than an
			// osculating-ellipse curve: the ellipse is wrong during non-Kepler phases
			// (flyby, capture burn), and even for a clean Kepler orbit its 512 points
			// span the whole loop, so a focused close-up quantises the head into a
			// visible kink. The buffer's live head sits exactly on the body and
			// densifies near it instead. Spans one osculating period, falling back to
			// the chunk window when elements are unavailable (mu=0 at first paint).
			let trailBuffer: TrailBuffer | undefined;
			{
				const { stepDays, epsilonScene, spanDays } = deriveProbeTrailParams(
					elements,
					endJd - startJd,
					NUM_TRAIL_POINTS
				);
				const cached = this.probeBuffers.get(id);
				if (cached && cached.parentKey === primaryKey) {
					trailBuffer = cached.buffer;
					// Heal a boot-time uniform buffer (elements unavailable at first
					// paint → Infinity) once elements resolve, without dropping the
					// accumulated samples.
					if (!isFinite(trailBuffer.epsilonScene) && isFinite(epsilonScene)) {
						trailBuffer.reconfigure(stepDays, epsilonScene, spanDays);
					}
				} else {
					trailBuffer = new TrailBuffer(NUM_TRAIL_POINTS, stepDays, epsilonScene, spanDays);
					trailBuffer.needsPopulate = true;
					this.probeBuffers.set(id, { buffer: trailBuffer, parentKey: primaryKey });
				}
			}
			result.push({
				data,
				position: null,
				// Kept even when the buffer drives the trail: the detail panel reads
				// these for its orbital-elements section (the trail path ignores them).
				orbitElements: elements ?? undefined,
				orbitCenterId: primaryKey,
				rederiveElements,
				trailBuffer
			});
		}
		// Surface every silent-drop path so a missing probe isn't just invisible.
		if (undefinedCenterProbes.size > 0) {
			console.error(
				`processProbes: ${undefinedCenterProbes.size} probe(s) have undefined fit_center_naif_id ` +
					`— metadata.json is stale (re-export to pick up fit_center_naif_id field). ` +
					`Affected probe ids: ${Array.from(undefinedCenterProbes).slice(0, 10).join(', ')}` +
					(undefinedCenterProbes.size > 10 ? ` (+${undefinedCenterProbes.size - 10} more)` : '')
			);
		}
		for (const [parentKey, probeIds] of missingGm) {
			console.warn(
				`processProbes: GM unavailable for ${parentKey} ` +
					`— kepler_pure sub-chunks will use mu=0 (static snapshot); ` +
					`affected ${probeIds.size} probe(s): ${Array.from(probeIds).slice(0, 5).join(', ')}` +
					(probeIds.size > 5 ? ` (+${probeIds.size - 5} more)` : '')
			);
		}
		return result;
	}

	/**
	 * Fetch + parse one minor-body chunk into columnar form, without building a
	 * per-row `PositionedBody`: the point cloud runs off the worker's per-frame
	 * solve, and the few bodies that become objects materialize on demand via
	 * {@link MinorBucket}.
	 */
	async fetchMinorColumns(
		zone: string,
		zoom: number | null,
		part: number,
		time: string | null = null,
		priority?: RequestPriority
	): Promise<ElementColumns> {
		return fetchElements(zone, zoom, part, time, priority);
	}

	/** One body per row of an elements file. The placement pass gives them
	 *  their places: a row whose parent is not loaded stays without one. */
	async process(
		zone: string,
		zoom: number | null,
		part: number,
		time: string | null = null,
		parentIdType: string = 'naif',
		priority?: RequestPriority
	): Promise<PositionedBody[]> {
		const firstPass = this.barycenters.size === 0;
		const bodies: PositionedBody[] = [];
		// Rows with no orbit to propagate. Tallied, not logged per body.
		let degenerate = 0;

		const [cols, labels] = await Promise.all([
			fetchElements(zone, zoom, part, time, priority),
			fetchLabels()
		]);

		const isParabolic = cols.kind === 'parabolic';
		const isSGP4 = cols.kind === 'sgp4';

		// Time-budgeted slicing: this loop runs for every row of every minor
		// chunk (~1M rows on a full load) — without yields it starves input
		// and rAF for seconds during phase 2.
		let sliceStart = performance.now();
		for (let idx = 0; idx < cols.rowCount; idx++) {
			if ((idx & 255) === 255 && performance.now() - sliceStart > 6) {
				await yieldToMain();
				sliceStart = performance.now();
			}
			const objType = cols.objectType[idx] as ObjectType;

			// Parabolic comets always have a valid orbit; for Keplerian/SGP4, skip
			// degenerate a=0 bodies (except structural barycenters/Lagrange points
			// and major bodies that orbit at their own barycenter, e.g. Mars).
			if (
				!isParabolic &&
				(cols as KeplerianColumns | SGP4Columns).a[idx] === 0 &&
				objType !== ObjectType.BARYCENTER &&
				objType !== ObjectType.LAGRANGE_POINT &&
				!isMajorBody(objType)
			) {
				degenerate++;
				continue;
			}

			const parentKey = `${parentIdType}-${cols.parentId[idx]}`;
			const body = isParabolic
				? parabolicToBody(cols as ParabolicColumns, idx, labels, parentIdType)
				: isSGP4
					? sgp4ToBody(cols as SGP4Columns, idx, labels, parentIdType)
					: keplerianToBody(cols as KeplerianColumns, idx, labels, parentIdType);
			if (!body) continue;
			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				// A barycenter about the SSB has no ellipse to lend.
				if (firstPass && body.a > 0 && body.e < 1) this.barycenters.set(body.id, body);
				bodies.push({
					data: body,
					position: null,
					orbitElements: body.a > 0 ? body : undefined,
					orbitCenterId: parentKey
				});
				continue;
			}

			if (isMajorBody(objType)) {
				const isMoon = objType === ObjectType.MOON;
				// A planet whose parent has barycenter elements borrows them: that
				// curve is about the barycentre of the Solar System. Any other body
				// has its own elements about its parent (Ceres about the Sun).
				const hasBarycenter = this.barycenters.has(parentKey);
				bodies.push({
					data: body,
					position: null,
					orbitElements: isMoon ? body : (this.barycenters.get(parentKey) ?? body),
					orbitCenterId: isMoon || !hasBarycenter ? parentKey : undefined
				});
			} else {
				bodies.push({ data: body, position: null });
			}
		}
		if (degenerate > 0) {
			console.debug(`process(${zone}/${zoom}/${part}): skipped ${degenerate} row(s) with a = 0`);
		}
		return bodies;
	}
}
