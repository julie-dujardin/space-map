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
import { OrbitalSource, Scale, chunkedPartedUrl, partedUrl } from '$lib/fetch/position/format';
import { parsePosition } from '$lib/fetch/position/parse';
import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types/objects';
import { AU_KM, AU_SCALE, KM3_S2_TO_AU3_DAY2 } from '$lib/math/units';
import { dateToJD } from '$lib/format/date';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { chebyshevPositionScene, chebyshevStateKm } from '$lib/fetch/position/chebyshev/propagate';
import type { ChebyshevBody } from '$lib/fetch/position/chebyshev/parse';
import { stateVectorToElements } from '$lib/math/orbit/state';
import { getGmKm3s2 } from '$lib/fetch/systems-global';

const KM_DAY_TO_AU_DAY = 1 / AU_KM;

/**
 * Osculating Keplerian elements from a chebyshev body's state at `jd`, with
 * the parent's GM. Returns null when the parent has no GM (SPICE coverage
 * hole or pre-load timing on `systems/global.json`), the chebyshev sample
 * misses, or the resulting state degenerates (radial / parabolic). The
 * snapshot drives the orbit-line curve through the same kepler path as
 * SBDB-sourced bodies — see `processChebyshev` below. The orbit-line refresh
 * path re-invokes this periodically via `PositionedBody.rederiveElements` to
 * keep the ellipse aligned with the actual chebyshev path as time advances
 * within a chunk.
 */
function chebyshevOsculatingElements(
	body: ChebyshevBody,
	parentNaifId: number,
	jd: number
): OrbitalElements | null {
	const gmKm3s2 = getGmKm3s2(parentNaifId);
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

function keplerianToBody(
	cols: KeplerianColumns,
	idx: number,
	labels: LabelMap,
	idMap: Map<number, string>
): BodyData {
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;
	const omDot = cols.omDot[idx];
	const wDot = cols.wDot[idx];
	const id = idMap.get(idx)!;
	return {
		id,
		name: pickLabel(labels, id),
		isMinor: pickIsMinor(labels, id),
		hasLocalized: cols.hasLocalized[idx] === 1,
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `naif-${cols.parentId[idx]}`,
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
	idMap: Map<number, string>
): BodyData {
	const id = idMap.get(idx)!;
	return {
		id,
		name: pickLabel(labels, id),
		isMinor: pickIsMinor(labels, id),
		hasLocalized: cols.hasLocalized[idx] === 1,
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `naif-${cols.parentId[idx]}`,
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
	idMap: Map<number, string>
): BodyData | null {
	const id = idMap.get(idx)!;
	const name = pickLabel(labels, id);
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
		isMinor: pickIsMinor(labels, id),
		hasLocalized: cols.hasLocalized[idx] === 1,
		objectType: cols.objectType[idx] as ObjectType,
		parentId: `naif-${cols.parentId[idx]}`,
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

	// Track positions by ID for parent lookups (not reactive — local computation only)
	positions = new Map<number, [number, number, number]>();
	// Store barycenter orbital elements for planet orbit drawing. Populated by
	// both `processChebyshev` (osculating elements derived from the polynomial
	// state) and `process` (elements ride-along from the binary chunks); the
	// chebyshev pass runs first so `process` sees barycenter elements when it
	// resolves a planet's parent.
	barycenters = new Map<number, OrbitalElements>();

	constructor(private readonly cheb: ChebyshevStore | null) {
		this.positions.set(0, [0, 0, 0]); // Solar System Barycenter
	}

	/**
	 * Build PositionedBody[] for every body in the chebyshev store covered by
	 * `date`. Skipped zones (chunk not loaded yet) drop their bodies — callers
	 * must `await store.ensure(jd).done` first.
	 *
	 * Walks bodies in two passes so children find their parents in `positions`:
	 *
	 *   1. Sort bodies so barycenters (object_type=BARYCENTER, naif_id < 100)
	 *      land before everything else — Earth-Moon barycenter (naif-3) is
	 *      Earth's parent, Sun (naif-10) is the parent of the planet
	 *      barycenters, SSB (naif-0) is the implicit root at scene origin.
	 *   2. For each body, evaluate its parent-relative chebyshev position,
	 *      shift by the parent's world position, and emit a PositionedBody.
	 *
	 * The body's `data` carries osculating Keplerian elements derived from the
	 * Chebyshev state (position + velocity) at `jd` plus the parent's GM. This
	 * is the same shape the SBDB/Horizons elements path produces, so the
	 * orbit-line builder draws a closed kepler curve through the unified path
	 * in {@link makeOrbitLine}. `a` from the derivation also serves the
	 * visibility-ratio code (`getMoonVisibility`, `getPlanetVisibility`).
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
			const parentPos = this.positions.get(body.parentNaifId) ?? this.positions.get(0)!;
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
			const elements = chebyshevOsculatingElements(body, body.parentNaifId, jd);
			// Re-derive callback used by the orbit-line refresh path. We can't
			// close over the `ChebyshevBody` reference here — those records
			// are *per-chunk*, so by the time the user crosses a chunk boundary
			// the captured ref no longer covers the new jd and rederive would
			// silently return null. Look up the live body each call via its
			// stable string id so the callback follows chunk transitions.
			const ownId = body.id;
			const ownRederive = (newJd: number): OrbitalElements | null => {
				const fresh = cheb.body(ownId, newJd);
				if (!fresh) return null;
				return chebyshevOsculatingElements(fresh, fresh.parentNaifId, newJd);
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
				parentId: `naif-${body.parentNaifId}`,
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
			if (writePositions) this.positions.set(body.naifId, pos);
			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				if (writePositions && elements && elements.a > 0 && elements.e < 1) {
					this.barycenters.set(body.naifId, elements);
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
				const parentElements = this.barycenters.get(body.parentNaifId);
				const orbitElements = isMoon ? elements : (parentElements ?? elements);
				const borrowedFromParent = !isMoon && parentElements !== undefined;
				// Borrowed bodies must re-derive against the *parent's* chebyshev,
				// since `orbitElements` traces the parent barycenter's orbit, not
				// the planet's wobble. Capture the parent's stable string id (not
				// the per-chunk body record — see `ownRederive` above) so the
				// callback resolves the live record each call.
				const parentChebId = chebBodiesByNaif.get(body.parentNaifId)?.id;
				const rederiveElements =
					borrowedFromParent && parentChebId
						? (newJd: number): OrbitalElements | null => {
								const fresh = cheb.body(parentChebId, newJd);
								if (!fresh) return null;
								return chebyshevOsculatingElements(fresh, fresh.parentNaifId, newJd);
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

	async process(
		zone: string,
		zoom: number,
		part: number,
		date: Date,
		time: string | null = null
	): Promise<PositionedBody[]> {
		const writePositions = this.barycenters.size === 0;
		const bodies: PositionedBody[] = [];

		const [cols, labels] = await Promise.all([
			fetchElements(zone, zoom, part, time),
			fetchLabels()
		]);
		const idMap = cols.idMap;

		console.log(`Loaded: ${cols.rowCount} objects`);
		const isParabolic = cols.kind === 'parabolic';
		const isSGP4 = cols.kind === 'sgp4';
		const jd = dateToJD(date);

		for (let idx = 0; idx < cols.rowCount; idx++) {
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

			const parentId = cols.parentId[idx];
			if (!this.positions.has(parentId)) {
				console.warn(`Parent position not found for parentId=${parentId}, falling back to origin`);
			}
			const parentPos = this.positions.get(parentId) ?? this.positions.get(0)!;

			const body = isParabolic
				? parabolicToBody(cols as ParabolicColumns, idx, labels, idMap)
				: isSGP4
					? sgp4ToBody(cols as SGP4Columns, idx, labels, idMap)
					: keplerianToBody(cols as KeplerianColumns, idx, labels, idMap);
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

			const id = cols.id[idx];

			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				if (writePositions) {
					// if parent is SSB, don't use it
					if (body.a > 0 && body.e < 1) {
						this.barycenters.set(id, body);
					}
					this.positions.set(id, pos);
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
				this.positions.set(id, pos);
			}

			if (isMajorBody(objType)) {
				const isMoon = objType === ObjectType.MOON;
				// If the parent has barycenter elements, draw the orbit around SSB
				// (centered at origin) using those elements. Otherwise the body's
				// own elements are around the parent (e.g. Ceres around the Sun),
				// so the orbit must be drawn centered on the parent's actual
				// position, not at SSB — failing to do so leaves the trail offset
				// from the body by parent_pos − SSB.
				const hasBarycenter = this.barycenters.has(parentId);
				bodies.push({
					data: body,
					position: pos,
					orbitElements: isMoon ? body : (this.barycenters.get(parentId) ?? body),
					orbitCenter: isMoon || !hasBarycenter ? parentPos : undefined
				});
			} else {
				bodies.push({
					data: body,
					position: pos
				});
			}
		}
		return bodies;
	}
}
