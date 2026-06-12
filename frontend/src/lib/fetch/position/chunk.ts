import { fetchLabels, type LabelMap } from '$lib/fetch/position/labels';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/orbit/position';
import { buildSatrec, sgp4PositionScene } from '$lib/math/orbit/sgp4';
import {
	type KeplerianColumns,
	type ParabolicColumns,
	type SGP4Columns,
	type ElementColumns
} from '$lib/fetch/position/elements/parse';
import { LruPromiseCache } from '$lib/fetch/position/cache';
import { isMajorBody } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { yieldToMain } from '$lib/yield';
import { OrbitalSource, Scale, chunkedPartedUrl, partedUrl } from '$lib/fetch/position/format';
import { parsePosition } from '$lib/fetch/position/parse';
import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types/objects';
import { AU_KM, AU_SCALE, KM3_S2_TO_AU3_DAY2, KM_DAY_TO_AU_DAY, kmToScene } from '$lib/math/units';
import { dateToJD } from '$lib/format/date';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { chebyshevPositionScene, chebyshevStateKm } from '$lib/fetch/position/chebyshev/propagate';
import type { ChebyshevBody } from '$lib/fetch/position/chebyshev/parse';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import { probePositionKm } from '$lib/fetch/position/probes/propagate';
import { probeOsculatingElements } from '$lib/fetch/position/probes/elements';
import { resolvePrimaryOverride } from '$lib/fetch/position/probes/primary';
import { populateProbeTrailBuffer } from '$lib/fetch/position/probes/trail';
import { stateVectorToElements } from '$lib/math/orbit/state';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import { NUM_TRAIL_POINTS } from '$lib/scene/objects/trail/points';
import { PROBE_METHOD_CHEBYSHEV } from '$lib/fetch/position/format';

/**
 * Osculating Keplerian elements from a chebyshev body's state at `jd`, with
 * the parent's GM. Returns null when the parent has no GM (SPICE coverage
 * hole or pre-load timing on `systems/global.json`), the chebyshev sample
 * misses, or the resulting state degenerates (radial / parabolic). The
 * snapshot drives the trail curve through the same kepler path as
 * SBDB-sourced bodies — see `processChebyshev` below. The trail refresh
 * path re-invokes this periodically via `PositionedBody.rederiveElements` to
 * keep the ellipse aligned with the actual chebyshev path as time advances
 * within a chunk.
 */
function chebyshevOsculatingElements(
	body: ChebyshevBody,
	parentId: number,
	jd: number
): OrbitalElements | null {
	const gmKm3s2 = getGmKm3s2(parentId);
	if (!gmKm3s2) return null;
	const state = chebyshevStateKm(body, jd);
	if (!state) return null;
	const muAuDay2 = gmKm3s2 * KM3_S2_TO_AU3_DAY2;
	const r: [number, number, number] = [
		state.position[0] / AU_KM,
		state.position[1] / AU_KM,
		state.position[2] / AU_KM
	];
	const v: [number, number, number] = [
		state.velocity[0] * KM_DAY_TO_AU_DAY,
		state.velocity[1] * KM_DAY_TO_AU_DAY,
		state.velocity[2] * KM_DAY_TO_AU_DAY
	];
	return stateVectorToElements(r, v, muAuDay2, jd);
}

/**
 * Resolve a label to a non-empty name or null. The labels file ships
 * `{id}\x1f\x1f` for promoted bodies with no Wikidata/DB name (the id
 * still needs to be in the keys so the renderer auto-promotes it).
 * Coalescing `''` to null here keeps `body.data.name` truthy-or-null,
 * so downstream `?? fallback` chains in the drawer / page title / focus
 * URL work.
 */
function pickLabel(labels: LabelMap, id: string): string | null {
	return labels.get(id)?.name || null;
}

function pickIsMinor(labels: LabelMap, id: string): boolean {
	return labels.get(id)?.isMinor ?? false;
}

/** Single-lookup variant of pickLabel + pickIsMinor for the per-row hot loops —
 *  two string-keyed gets per row measured ~10% of the asteroid-load window. */
function pickLabelEntry(labels: LabelMap, id: string): { name: string | null; isMinor: boolean } {
	const entry = labels.get(id);
	return { name: entry?.name || null, isMinor: entry?.isMinor ?? false };
}

function keplerianToBody(
	cols: KeplerianColumns,
	idx: number,
	labels: LabelMap,
	idMap: Map<number, string>,
	parentIdType: string
): BodyData {
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;
	const omDot = cols.omDot[idx];
	const wDot = cols.wDot[idx];
	const id = idMap.get(idx)!;
	const { name, isMinor } = pickLabelEntry(labels, id);
	return {
		id,
		name,
		isMinor,
		hasLocalized: cols.hasLocalized[idx] === 1,
		flags: cols.flags[idx],
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `${parentIdType}-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		// Planet-scale: a is in km, n is in rev/day → convert to AU and deg/day
		a: isPlanetScale ? cols.a[idx] / AU_KM : cols.a[idx],
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: cols.ma[idx],
		n: isPlanetScale ? cols.n[idx] * 360 : cols.n[idx],
		epoch: cols.epochJd[idx],
		omDot: omDot !== 0 ? omDot : undefined,
		wDot: wDot !== 0 ? wDot : undefined,
		// Planet-scale entries come from CelesTrak TLEs, whose angles are in the
		// Earth-equatorial (TEME) frame. System-scale entries are ecliptic J2000.
		equatorial: isPlanetScale,
		validityStart: cols.validityStart,
		validityEnd: cols.validityEnd,
		orbitalSource: cols.source
	};
}

function parabolicToBody(
	cols: ParabolicColumns,
	idx: number,
	labels: LabelMap,
	idMap: Map<number, string>,
	parentIdType: string
): BodyData {
	const id = idMap.get(idx)!;
	const { name, isMinor } = pickLabelEntry(labels, id);
	return {
		id,
		name,
		isMinor,
		hasLocalized: cols.hasLocalized[idx] === 1,
		flags: cols.flags[idx],
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `${parentIdType}-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		a: 0,
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: 0,
		n: 0,
		epoch: cols.epochJd[idx],
		q: cols.q[idx],
		tp: cols.tp[idx],
		validityStart: cols.validityStart,
		validityEnd: cols.validityEnd,
		orbitalSource: cols.source
	};
}

/**
 * Build an SGP4-backed BodyData for one earth satellite. Returns null when
 * satrec init fails — earth sats must use SGP4, so we drop the row rather
 * than silently falling back to Kepler (which diverges from the SGP4 curve
 * by km and breaks trail construction).
 */
function sgp4ToBody(
	cols: SGP4Columns,
	idx: number,
	labels: LabelMap,
	idMap: Map<number, string>,
	parentIdType: string
): BodyData | null {
	const id = idMap.get(idx)!;
	const { name, isMinor } = pickLabelEntry(labels, id);
	const satrec = buildSatrec(
		{
			noradCatId: cols.id[idx],
			epochJd: cols.epochJd[idx],
			meanMotion: cols.n[idx],
			eccentricity: cols.e[idx],
			inclination: cols.i[idx],
			raOfAscNode: cols.om[idx],
			argOfPericenter: cols.w[idx],
			meanAnomaly: cols.ma[idx],
			bstar: cols.bstar[idx],
			meanMotionDot: cols.meanMotionDot[idx],
			meanMotionDdot: cols.meanMotionDdot[idx],
			elementSetNo: cols.elementSetNo[idx],
			revAtEpoch: cols.revAtEpoch[idx]
		},
		name ?? undefined
	);
	if (!satrec) return null;
	return {
		id,
		name,
		isMinor,
		hasLocalized: cols.hasLocalized[idx] === 1,
		flags: cols.flags[idx],
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `${parentIdType}-${cols.parentId[idx]}`,
		radiusKm: cols.radiusKm[idx],
		// Kepler mean elements kept in canonical (AU, deg/day) units for the
		// orbit-period estimate used by sgp4Curve — they're not used to propagate.
		a: cols.a[idx] / AU_KM,
		e: cols.e[idx],
		i: cols.i[idx],
		om: cols.om[idx],
		w: cols.w[idx],
		ma: cols.ma[idx],
		n: cols.n[idx] * 360,
		epoch: cols.epochJd[idx],
		equatorial: true,
		satrec,
		validityStart: cols.validityStart,
		validityEnd: cols.validityEnd,
		orbitalSource: cols.source
	};
}

/**
 * Build the URL for an elements-payload position file. Static parted zones
 * (most SBDB zones, spacecraft) skip the time component; chunked-parted zones
 * (earth date-segmented, moons chunk-indexed) inject it as a path segment.
 *
 * Chebyshev zones don't go through this loader — they're handled by the
 * `ChebyshevStore`'s own URL builder (`chunkedUrl`) and don't carry parts.
 */
function elementsUrl(zone: string, zoom: number, part: number, time: string | null): string {
	return time ? chunkedPartedUrl(zone, zoom, time, part) : partedUrl(zone, zoom, part);
}

/**
 * Capacity for the parsed-elements cache. Sized to comfortably hold the
 * Earth-sat hot-reload window (a handful of recent snapshots) plus a few
 * other zones the user might bounce between. Each entry retains the parsed
 * typed-array views and their ArrayBuffer — Earth's ~25K rows are ~5–10 MB.
 */
const PARSED_ELEMENTS_CACHE_CAPACITY = 8;
const elementsCache = new LruPromiseCache<ElementColumns>(PARSED_ELEMENTS_CACHE_CAPACITY);

async function fetchElements(
	zone: string,
	zoom: number,
	part: number,
	time: string | null
): Promise<ElementColumns> {
	const key = `${zone}:${zoom}:${part}:${time ?? ''}`;
	return elementsCache.getOrCompute(key, async () => {
		const res = await fetch(elementsUrl(zone, zoom, part, time));
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
	static prefetch(zone: string, zoom: number, part: number, time: string | null = null): void {
		fetch(elementsUrl(zone, zoom, part, time));
	}

	/** Positions by full Object.id (e.g. "naif-399", "spkid-2000004"). String-keyed
	 *  so zones with different parent prefixes don't collide on the numeric portion. */
	positions = new Map<string, [number, number, number]>();
	/** Barycenter elements used for planet orbit drawing. `processChebyshev`
	 *  populates first (so `process` sees them when resolving planet parents). */
	barycenters = new Map<string, OrbitalElements>();
	/** Body IDs whose positions must be retained even when the body would
	 *  normally be skipped from `positions` (writePositions=false / non-major).
	 *  Seeded by the orchestrator with the parent IDs needed by downstream zones
	 *  (e.g. `small_body_moons` parents whose asteroid bodies live in
	 *  `small_bodies/*` zones — without this set, asteroid-moon parents would
	 *  never end up in `positions` and the moons would skip / fall back). */
	neededParentIds = new Set<string>();

	/**
	 * Past-position ring buffers for probes whose chunk has at least one
	 * chebyshev sub-chunk. Keyed by probe.id and tagged with the current
	 * parent key; when the probe crosses zones the parent flips and the
	 * stored entries (in the OLD parent's frame) get cleared. Owned here so
	 * accumulated trail history survives chunk-load passes — `processProbes`
	 * mutates this map but never replaces it.
	 */
	private readonly probeBuffers = new Map<string, { buffer: TrailBuffer; parentKey: string }>();

	constructor(private readonly cheb: ChebyshevStore | null) {
		this.positions.set('naif-0', [0, 0, 0]); // Solar System Barycenter
	}

	/**
	 * Build PositionedBody[] for every chebyshev body covered by `date`. Caller
	 * must `await store.ensure(jd).done` first; zones with no loaded chunk are
	 * skipped. Walks in barycenter-first order so children resolve parents from
	 * `positions`. Each body carries osculating Keplerian elements derived from
	 * the chebyshev state + parent GM, matching the SBDB/Horizons shape so the
	 * trail builder uses the unified kepler curve in {@link makeTrail}.
	 */
	processChebyshev(date: Date, labels: LabelMap): PositionedBody[] {
		if (!this.cheb) return [];
		const jd = dateToJD(date);
		const writePositions = this.barycenters.size === 0;
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
			const tierA =
				a.body.objectType === ObjectType.BARYCENTER
					? 0
					: a.body.objectType === ObjectType.STAR
						? 1
						: 2;
			const tierB =
				b.body.objectType === ObjectType.BARYCENTER
					? 0
					: b.body.objectType === ObjectType.STAR
						? 1
						: 2;
			return tierA - tierB || a.body.naifId - b.body.naifId;
		});

		const cheb = this.cheb;
		for (const { body, startJd, endJd } of all) {
			const offset = chebyshevPositionScene(body, jd);
			if (!offset) continue;
			chebBodiesByNaif.set(body.naifId, body);
			const parentKey = `naif-${body.parentId}`;
			const parentPos = this.positions.get(parentKey);
			if (!parentPos) {
				// Chebyshev bodies are sorted parents-first so the parent should
				// always be resolved by the time we reach this child. A miss
				// here means the ephemeris carries a body whose parent isn't in
				// the chebyshev set — hide it rather than anchoring it at the
				// origin (which would visually misplace the body and pollute
				// trail derivation).
				console.warn(
					`processChebyshev: parent ${parentKey} not in positions for ${body.id} — hiding`
				);
				continue;
			}
			const pos: [number, number, number] = [
				parentPos[0] + offset[0],
				parentPos[1] + offset[1],
				parentPos[2] + offset[2]
			];
			const objType = body.objectType as ObjectType;
			// Osculating elements snapshot: position + velocity from the
			// polynomial, parent GM from the global systems file. Returns null
			// when the parent has no GM (out-of-coverage in SPICE) or the
			// state is degenerate; the body still gets a position-only entry
			// so it can render, just without an orbit curve.
			const elements = chebyshevOsculatingElements(body, body.parentId, jd);
			// Re-derive callback used by the trail refresh path. We can't
			// close over the `ChebyshevBody` reference here — those records
			// are *per-chunk*, so by the time the user crosses a chunk boundary
			// the captured ref no longer covers the new jd and rederive would
			// silently return null. Look up the live body each call via its
			// stable string id so the callback follows chunk transitions.
			const ownId = body.id;
			const ownRederive = (newJd: number): OrbitalElements | null => {
				const fresh = cheb.body(ownId, newJd);
				if (!fresh) return null;
				return chebyshevOsculatingElements(fresh, fresh.parentId, newJd);
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
				validityStart: startJd,
				validityEnd: endJd,
				orbitalSource: OrbitalSource.SPICE
			};
			if (writePositions) this.positions.set(body.id, pos);
			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				if (writePositions && elements && elements.a > 0 && elements.e < 1) {
					this.barycenters.set(body.id, elements);
				}
				result.push({
					data,
					position: pos,
					orbitElements: elements ?? undefined,
					orbitCenter: parentPos,
					rederiveElements: ownRederive
				});
				continue;
			}
			if (isMajorBody(objType)) {
				// Mirror the elements path: planets use the parent barycenter's
				// orbit (the planet's own offset is just wobble); moons use
				// their own. When borrowing barycenter elements, leave
				// `orbitCenter` undefined so the curve is drawn at SSB —
				// otherwise the heliocentric ellipse would land on the planet.
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
					position: pos,
					orbitElements: orbitElements ?? undefined,
					orbitCenter: borrowedFromParent ? undefined : parentPos,
					// The borrowed curve traces the *barycenter*'s orbit, so the
					// trail's bright end belongs on the barycenter. Fresh array
					// (not the shared `parentPos` ref) so the per-frame mutator
					// can update it independently from the parent's own object.
					trailAnchor: borrowedFromParent ? [parentPos[0], parentPos[1], parentPos[2]] : undefined,
					rederiveElements
				});
			} else {
				result.push({
					data,
					position: pos,
					orbitElements: elements ?? undefined,
					orbitCenter: parentPos,
					rederiveElements: ownRederive
				});
			}
		}
		return result;
	}

	/**
	 * Build PositionedBody[] for every probe whose current chunk is resident
	 * in `probeStore`. Mirrors `processChebyshev` but for spacecraft probes:
	 *
	 *   1. Iterate `probeStore.probesAt(jd)` — yields one entry per probe whose
	 *      chunk for jd is loaded, deduped across zones (a flyby probe lives in
	 *      both the planet zone and interplanetary; the store collapses them).
	 *      The per-frame propagator re-resolves with the focused-system filter
	 *      and flips parentId when the user zooms into a planet's zone.
	 *   2. Resolve the fit-center body (Sun for `probes/interplanetary`,
	 *      Mercury for `probes/mercury`, …) in `this.positions` — chebyshev
	 *      must have run first so these are present.
	 *   3. Look up GM(km³/s²) for the fit center; without it Kepler-pure
	 *      sub-chunks can't be evaluated (no `sqrt(mu/a³)` for M drift).
	 *      systems-global may not be loaded yet at first paint; the renderer
	 *      retries each frame so eventual consistency catches up.
	 *
	 * The returned `BodyData` carries zero osculating elements (the fit methods
	 * produce position directly, no need to round-trip through Kepler for the
	 * body itself). Trail handling splits per probe:
	 *
	 *   - **Pure Kepler** (no chebyshev sub-chunks anywhere in the probe): the
	 *     `PositionedBody`'s `orbitElements` + `rederiveElements` carry a
	 *     per-sub-chunk osculating snapshot. `refreshTrail`
	 *     re-snapshots periodically so the curve tracks the next sub-chunk
	 *     across boundaries.
	 *   - **Has at least one chebyshev sub-chunk**: a `TrailBuffer` of past
	 *     sampled positions takes over. `orbitElements` is left undefined so
	 *     the trail builder takes the buffer codepath; the buffer is
	 *     back-filled here against the current parent's frame and appended to
	 *     each frame by `updatePositions`. An osculating ellipse misrepresents
	 *     a flyby / capture / depart maneuver, so we polyline the real path.
	 *
	 * `validityStart/End` come from the chunk's common-header bounds, used by
	 * the renderer to hide a probe whose chunk isn't loaded yet rather than
	 * render a stale position.
	 */
	processProbes(probeStore: ProbeStore, date: Date, labels: LabelMap): PositionedBody[] {
		const jd = dateToJD(date);
		const result: PositionedBody[] = [];
		const missingParents = new Map<string, Set<string>>(); // parentKey → probe ids
		const missingGm = new Map<string, Set<string>>(); // "naif-<id>" or "naif-undefined" → probe ids
		const nullOffsets = new Set<string>();
		const undefinedCenterProbes = new Set<string>();
		// `probesAt` dedupes per probe.id. At boot there's no focused system,
		// so the initial zone wins by metadata order (interplanetary first);
		// the per-frame propagator flips parentId when zooming into a planet.
		for (const { probe, zoneCenterNaifId, startJd, endJd } of probeStore.probesAt(jd)) {
			if (!probe.id) continue;
			if (zoneCenterNaifId === undefined) undefinedCenterProbes.add(probe.id);
			const zoneCenterKey = `naif-${zoneCenterNaifId}`;
			// Resolve the probe's *actual* fit center: the writer-stamped
			// override (Moon for lunar orbiters, Titan for Cassini-at-Titan, …)
			// or the zone center when there's no override. Sub-chunks were fit
			// against that body, so its NAIF + GM + world position drive both
			// the propagator and the anchor.
			const override = resolvePrimaryOverride(probe, jd, zoneCenterKey, this.cheb);
			const primaryKey = override ? override.id : zoneCenterKey;
			const primaryNaif = override ? override.naifId : zoneCenterNaifId;
			const primaryMu = primaryNaif === undefined ? 0 : (getGmKm3s2(primaryNaif) ?? 0);
			const primaryPos = this.positions.get(primaryKey);
			if (!primaryPos) {
				let s = missingParents.get(primaryKey);
				if (!s) missingParents.set(primaryKey, (s = new Set()));
				s.add(probe.id);
			}
			if (primaryMu === 0) {
				let s = missingGm.get(primaryKey);
				if (!s) missingGm.set(primaryKey, (s = new Set()));
				s.add(probe.id);
			}
			const offsetKm = probePositionKm(probe, jd, primaryMu);
			if (!offsetKm) nullOffsets.add(probe.id);
			const anchor = primaryPos ?? this.positions.get('naif-0')!;
			const offset: [number, number, number] | null = offsetKm
				? [kmToScene(offsetKm[0]), kmToScene(offsetKm[2]), -kmToScene(offsetKm[1])]
				: null;
			// Probe outside its sub-chunk windows at this jd (e.g. chunk
			// straddles its inception) — emit a position-only entry at the
			// parent's location; the per-frame propagator hides it.
			const pos: [number, number, number] = offset
				? [anchor[0] + offset[0], anchor[1] + offset[1], anchor[2] + offset[2]]
				: [anchor[0], anchor[1], anchor[2]];
			const data: BodyData = {
				id: probe.id,
				name: pickLabel(labels, probe.id),
				isMinor: pickIsMinor(labels, probe.id),
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
			// Re-read live probe record AND its current zone's fit center on
			// every call: scrubbing the timeline can move the probe into a
			// different chunk (per-chunk Probe ref goes stale) or a different
			// zone with a different fit center (cruise → captured orbit). A
			// late-arriving systems-global GM table also self-heals on the next
			// periodic re-derive. Mirrors the chebyshev rederive pattern
			// (`ownRederive` in processChebyshev).
			const ownId = probe.id;
			const cheb = this.cheb;
			const rederiveElements = (newJd: number): OrbitalElements | null => {
				const located = probeStore.probeWithCenter(ownId, newJd);
				if (!located) return null;
				const freshZoneKey = `naif-${located.fitCenterNaifId}`;
				const freshOverride = resolvePrimaryOverride(located.probe, newJd, freshZoneKey, cheb);
				const freshPrimaryNaif = freshOverride ? freshOverride.naifId : located.fitCenterNaifId;
				const freshPrimaryMu = getGmKm3s2(freshPrimaryNaif) ?? 0;
				return probeOsculatingElements(located.probe, newJd, freshPrimaryMu);
			};
			// Trail-buffer path for probes with any chebyshev sub-chunk: an
			// osculating-ellipse trail is meaningless during a non-Kepler phase
			// (planetary flyby, capture/depart maneuver), so sample real past
			// positions instead. Probes that are pure Kepler stay on the
			// orbit-elements codepath above. Buffer is sized by the osculating
			// period when available (closes the loop after one orbit); falls back
			// to the current chunk's window when elements can't be derived
			// (mu=0 at first paint, degenerate chebyshev FD).
			const hasChebyshev = probe.subChunks.some((sc) => sc.method === PROBE_METHOD_CHEBYSHEV);
			let trailBuffer: TrailBuffer | undefined;
			if (hasChebyshev) {
				const periodDays = elements && elements.n > 0 ? 360 / elements.n : endJd - startJd;
				const stepDays = periodDays > 0 ? periodDays / NUM_TRAIL_POINTS : 1;
				// Chord-error tolerance for adaptive trail sampling: a small
				// fraction of the orbit's semi-major axis (in scene units).
				// Falls back to Infinity (uniform sampling) when osculating
				// elements aren't available yet — the next periodic re-derive
				// will rebuild with proper ε.
				const epsilonScene = elements && elements.a > 0 ? elements.a * AU_SCALE * 0.0001 : Infinity;
				const cached = this.probeBuffers.get(probe.id);
				if (cached && cached.parentKey === primaryKey) {
					trailBuffer = cached.buffer;
				} else {
					trailBuffer = new TrailBuffer(NUM_TRAIL_POINTS, stepDays, epsilonScene);
					populateProbeTrailBuffer(trailBuffer, probeStore, cheb, probe.id, primaryKey, jd);
					this.probeBuffers.set(probe.id, { buffer: trailBuffer, parentKey: primaryKey });
				}
			}
			result.push({
				data,
				position: pos,
				// Pass elements through even when the buffer drives trail rendering:
				// the detail panel reads orbitElements to populate its orbital-elements
				// section. The trail refresh path early-returns on trailBuffer before
				// touching elements/rederive, so this is free for trail rendering.
				orbitElements: elements ?? undefined,
				// Private array, not a shared reference to the fit center body's position:
				// a probe's parent can flip between frames as it crosses zones.
				orbitCenter: [anchor[0], anchor[1], anchor[2]],
				rederiveElements,
				trailBuffer
			});
		}
		// Surface every silent-drop path so missing probes don't render as just
		// "you don't see it on screen". Deduped to keep the console legible.
		if (undefinedCenterProbes.size > 0) {
			console.error(
				`processProbes: ${undefinedCenterProbes.size} probe(s) have undefined fit_center_naif_id ` +
					`— metadata.json is stale (re-export to pick up fit_center_naif_id field). ` +
					`Affected probe ids: ${Array.from(undefinedCenterProbes).slice(0, 10).join(', ')}` +
					(undefinedCenterProbes.size > 10 ? ` (+${undefinedCenterProbes.size - 10} more)` : '')
			);
		}
		for (const [parentKey, probeIds] of missingParents) {
			console.warn(
				`processProbes: fit-center ${parentKey} not in positions ` +
					`(anchored at SSB) — ${probeIds.size} probe(s): ${Array.from(probeIds).slice(0, 5).join(', ')}` +
					(probeIds.size > 5 ? ` (+${probeIds.size - 5} more)` : '')
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
		if (nullOffsets.size > 0) {
			console.warn(
				`processProbes: ${nullOffsets.size} probe(s) outside sub-chunk windows at load ` +
					`(will stay hidden until jd enters coverage): ` +
					`${Array.from(nullOffsets).slice(0, 5).join(', ')}` +
					(nullOffsets.size > 5 ? ` (+${nullOffsets.size - 5} more)` : '')
			);
		}
		return result;
	}

	/**
	 * Fetch + parse a zone's elements file and register every row's parent ID
	 * in `neededParentIds`. Call before processing zones whose parents live in
	 * a different zone (e.g. `small_body_moons` parents in `small_bodies/*`) —
	 * without pre-registration, the parent's `process()` pass drops the
	 * position and the dependent body would skip.
	 */
	async seedNeededParents(
		zone: string,
		zoom: number,
		part: number,
		time: string | null,
		parentIdType: string
	): Promise<void> {
		const cols = await fetchElements(zone, zoom, part, time);
		for (let i = 0; i < cols.rowCount; i++) {
			this.neededParentIds.add(`${parentIdType}-${cols.parentId[i]}`);
		}
	}

	async process(
		zone: string,
		zoom: number,
		part: number,
		date: Date,
		time: string | null = null,
		parentIdType: string = 'naif'
	): Promise<PositionedBody[]> {
		const writePositions = this.barycenters.size === 0;
		const bodies: PositionedBody[] = [];
		const skippedMissingParent = new Map<string, number>();

		const [cols, labels] = await Promise.all([
			fetchElements(zone, zoom, part, time),
			fetchLabels()
		]);
		const idMap = cols.idMap;

		const isParabolic = cols.kind === 'parabolic';
		const isSGP4 = cols.kind === 'sgp4';
		const jd = dateToJD(date);

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
				continue;
			}

			const parentKey = `${parentIdType}-${cols.parentId[idx]}`;
			const parentPos = this.positions.get(parentKey);
			if (!parentPos) {
				// Hide the body: the SSB fallback used to anchor it at the
				// origin, which placed asteroid moons (whose NEO parents aren't
				// chebyshev perturbers) at the wrong scene location. Tally by
				// parent so the post-loop log groups them.
				skippedMissingParent.set(parentKey, (skippedMissingParent.get(parentKey) ?? 0) + 1);
				continue;
			}

			const body = isParabolic
				? parabolicToBody(cols as ParabolicColumns, idx, labels, idMap, parentIdType)
				: isSGP4
					? sgp4ToBody(cols as SGP4Columns, idx, labels, idMap, parentIdType)
					: keplerianToBody(cols as KeplerianColumns, idx, labels, idMap, parentIdType);
			// sgp4ToBody returns null when satrec init fails — drop the row to
			// enforce SGP4-only propagation for earth sats.
			if (!body) continue;
			// If the load-time jd is outside the chunk's validity window (e.g.
			// user URL-loaded a far-future date), seed with the parent position.
			// The per-frame propagation gate keeps the body hidden until jd
			// re-enters range.
			const inRange = jd >= body.validityStart && jd <= body.validityEnd;
			const offset = !inRange
				? ([0, 0, 0] as [number, number, number])
				: body.satrec
					? sgp4PositionScene(body.satrec, jd)
					: body.a === 0 && !isParabolic
						? ([0, 0, 0] as [number, number, number])
						: body.q != null
							? parabolicToPosition(body, date)
							: orbitalElementsToPosition(body, date);
			if (!offset) {
				console.warn(
					`Failed to compute position for body id=${body.id} name=${body.name} (e=${body.e})`
				);
				continue;
			}
			const pos: [number, number, number] = [
				parentPos[0] + offset[0],
				parentPos[1] + offset[1],
				parentPos[2] + offset[2]
			];

			// Retain positions of bodies that downstream zones need as parents
			// (e.g. asteroid hosts of `small_body_moons`). The normal stores
			// below only fire for barycenters / Lagrange points / major bodies,
			// so without this an asteroid parent would never land in
			// `this.positions`.
			if (this.neededParentIds.has(body.id)) {
				this.positions.set(body.id, pos);
			}

			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				if (writePositions) {
					// if parent is SSB, don't use it
					if (body.a > 0 && body.e < 1) {
						this.barycenters.set(body.id, body);
					}
					this.positions.set(body.id, pos);
				}
				bodies.push({
					data: body,
					position: pos,
					orbitElements: body.a > 0 ? body : undefined,
					orbitCenter: parentPos
				});
				continue;
			}

			if (writePositions && isMajorBody(objType)) {
				this.positions.set(body.id, pos);
			}

			if (isMajorBody(objType)) {
				const isMoon = objType === ObjectType.MOON;
				// If the parent has barycenter elements, draw the orbit around SSB
				// (centered at origin) using those elements. Otherwise the body's
				// own elements are around the parent (e.g. Ceres around the Sun),
				// so the orbit must be drawn centered on the parent's actual
				// position, not at SSB — failing to do so leaves the trail offset
				// from the body by parent_pos − SSB.
				const hasBarycenter = this.barycenters.has(parentKey);
				bodies.push({
					data: body,
					position: pos,
					orbitElements: isMoon ? body : (this.barycenters.get(parentKey) ?? body),
					orbitCenter: isMoon || !hasBarycenter ? parentPos : undefined
				});
			} else {
				bodies.push({
					data: body,
					position: pos
				});
			}
		}
		if (skippedMissingParent.size > 0) {
			const total = Array.from(skippedMissingParent.values()).reduce((a, b) => a + b, 0);
			const entries = Array.from(skippedMissingParent.entries())
				.map(([k, n]) => `${k}×${n}`)
				.join(', ');
			console.warn(
				`process(${zone}/${zoom}/${part}): hid ${total} body(ies) with unresolved parent — ${entries}`
			);
		}
		return bodies;
	}
}
