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
import { AU_KM, AU_SCALE } from '$lib/math/units';
import { dateToJD } from '$lib/format/date';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import { chebyshevPositionScene } from '$lib/fetch/position/chebyshev/propagate';
import { TrailBuffer } from '$lib/fetch/position/trail-buffer';

/**
 * Fill `buf` with up to `capacity` chebyshev samples ending at `centerJd`,
 * stepping back by `buf.stepDays`. Nulls (samples outside the body's segment
 * coverage) are skipped, so outer planets with limited chebyshev history
 * start with a partial buffer and grow as time plays.
 */
export function populateTrailBuffer(
	buf: TrailBuffer,
	store: ChebyshevStore,
	targetId: string,
	centerJd: number
): void {
	// Oldest first so the ring buffer's internal order is past → present.
	for (let k = buf.capacity - 1; k >= 0; k--) {
		const t = centerJd - k * buf.stepDays;
		const p = store.positionScene(targetId, t);
		if (p) buf.append(t, p[0], p[1], p[2]);
	}
}

/**
 * Resolve a label to a non-empty name or null. The labels file ships
 * `{id}\x1f` for promoted bodies with no Wikidata/DB name (the id still
 * needs to be in the keys so the renderer auto-promotes it). Coalescing
 * `''` to null here keeps `body.data.name` truthy-or-null, so downstream
 * `?? fallback` chains in the drawer / page title / focus URL work.
 */
function pickLabel(labels: LabelMap, id: string): string | null {
	return labels.get(id) || null;
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
	// Store barycenter orbital elements for planet orbit drawing
	barycenters = new Map<number, OrbitalElements>();

	/**
	 * Chebyshev trail buffers keyed by the body's string id. Owned by the
	 * ContextManager (persists across `process` calls so accumulated history
	 * survives chunk loads).
	 */
	constructor(
		private readonly cheb: ChebyshevStore | null,
		private readonly chebBuffers: Map<string, TrailBuffer>
	) {
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
	 * `a` (semi-major axis) is approximated by the position-vector magnitude at
	 * `jd` so the visibility-ratio code (`getMoonVisibility`,
	 * `getPlanetVisibility`) has a meaningful number without us having to ship
	 * Kepler elements alongside the chebyshev coefficients. The exact value
	 * matters for threshold ratios, not for propagation — the position itself
	 * comes from the polynomials.
	 */
	processChebyshev(date: Date, labels: LabelMap): PositionedBody[] {
		if (!this.cheb) return [];
		const jd = dateToJD(date);
		const writePositions = this.barycenters.size === 0;
		const result: PositionedBody[] = [];

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

		for (const { body, startJd, endJd } of all) {
			const offset = chebyshevPositionScene(body, jd);
			if (!offset) continue;
			const parentPos = this.positions.get(body.parentNaifId) ?? this.positions.get(0)!;
			const pos: [number, number, number] = [
				parentPos[0] + offset[0],
				parentPos[1] + offset[1],
				parentPos[2] + offset[2]
			];
			// Position-magnitude proxy for the visibility-ratio code (camera
			// distance / a). Cheb gives parent-relative offsets in scene units,
			// so dividing by AU_SCALE recovers the same AU-magnitude semantics
			// the elements path produces from `body.data.a`.
			const aAU = Math.hypot(offset[0], offset[1], offset[2]) / AU_SCALE;
			const objType = body.objectType as ObjectType;
			const data: BodyData = {
				id: body.id,
				name: pickLabel(labels, body.id),
				hasLocalized: body.hasLocalized,
				objectType: objType,
				parentId: `naif-${body.parentNaifId}`,
				radiusKm: body.radiusKm,
				a: aAU,
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
				orbitalSource: OrbitalSource.SPICE
			};
			if (writePositions) this.positions.set(body.naifId, pos);
			// Trail buffer is owned by the ContextManager — set it up later when
			// it knows the rendering period; here we just emit the body.
			if (objType === ObjectType.BARYCENTER || objType === ObjectType.LAGRANGE_POINT) {
				result.push({ data, position: pos, orbitCenter: parentPos });
				continue;
			}
			if (isMajorBody(objType)) {
				const isMoon = objType === ObjectType.MOON;
				result.push({
					data,
					position: pos,
					orbitCenter: parentPos,
					...(isMoon ? {} : {})
				});
			} else {
				result.push({ data, position: pos });
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
