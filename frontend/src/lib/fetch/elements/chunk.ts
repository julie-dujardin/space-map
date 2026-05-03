import { fetchLabels } from '$lib/fetch/elements/fetch';
import { orbitalElementsToPosition, parabolicToPosition } from '$lib/math/orbit/position';
import { buildSatrec, sgp4PositionScene } from '$lib/math/orbit/sgp4';
import {
	fetchElements,
	type KeplerianColumns,
	type ParabolicColumns,
	type SGP4Columns
} from '$lib/fetch/elements/elements';
import { isMajorBody } from '$lib/types/objects';
import { ObjectType } from '$lib/types/objects';
import { Scale, elementsBinUrl, elementLabelsUrl } from './constants';
import { type BodyData, type PositionedBody, type OrbitalElements } from '$lib/types/objects';
import { getLocale } from '$lib/paraglide/runtime.js';
import { AU_KM } from '$lib/math/units';
import { dateToJD } from '$lib/format/date';
import type { ChebyshevStore } from '$lib/fetch/chebyshev/store';
import { TrailBuffer } from '$lib/fetch/chebyshev/trail-buffer';
import { NUM_ORBIT_POINTS } from '$lib/scene/objects/builders';

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

function keplerianToBody(
	cols: KeplerianColumns,
	idx: number,
	labels: Map<number, string>,
	flags: Map<number, number>,
	idMap: Map<number, string>
): BodyData {
	const isPlanetScale = cols.scale[idx] === Scale.PLANET;
	const omDot = cols.omDot[idx];
	const wDot = cols.wDot[idx];
	return {
		id: idMap.get(idx)!,
		name: labels.get(idx) ?? null,
		objectFileFlag: flags.get(idx) ?? 0,
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
	labels: Map<number, string>,
	flags: Map<number, number>,
	idMap: Map<number, string>
): BodyData {
	return {
		id: idMap.get(idx)!,
		name: labels.get(idx) ?? null,
		objectFileFlag: flags.get(idx) ?? 0,
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
	labels: Map<number, string>,
	flags: Map<number, number>,
	idMap: Map<number, string>
): BodyData | null {
	const name = labels.get(idx) ?? null;
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
		id: idMap.get(idx)!,
		name,
		objectFileFlag: flags.get(idx) ?? 0,
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

export class ChunkLoader {
	/**
	 * Fire-and-forget fetch of the two files for a zone/zoom/part, so the browser
	 * caches them before the caller needs to process them. IDs ride inside the
	 * binary now (header id-type byte + column 0).
	 */
	static prefetch(zone: string, zoom: number, part: number, time: string | null = null): void {
		const lang = getLocale();
		fetch(elementsBinUrl(zone, zoom, part, time));
		fetch(elementLabelsUrl(lang, zone, zoom, part, time));
	}

	// Track positions by ID for parent lookups (not reactive — local computation only)
	positions = new Map<number, [number, number, number]>();
	// Store barycenter orbital elements for planet orbit drawing
	barycenters = new Map<number, OrbitalElements>();

	/**
	 * Chebyshev trail buffers keyed by the body's string id. Owned by the
	 * ContextManager (persists across `process` calls so accumulated history
	 * survives chunk loads); the loader populates entries here when it first
	 * sees a chebyshev-tracked body.
	 *
	 * Planets borrow their parent barycenter's buffer (via `bodyOwnTrailTargetId`);
	 * moons and barycenters use their own. This mirrors the Keplerian
	 * `barycenters` → planet-orbit wiring.
	 *
	 * TODO: remove the Keplerian `n` dependency once chebyshev ships periods
	 * per body — currently we still need the elements chunk loaded to get the
	 * orbital period for the buffer step size.
	 */
	constructor(
		private readonly cheb: ChebyshevStore | null,
		private readonly chebBuffers: Map<string, TrailBuffer>
	) {
		this.positions.set(0, [0, 0, 0]); // Solar System Barycenter
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

		const [cols, labelData] = await Promise.all([
			fetchElements(zone, zoom, part, time),
			fetchLabels(zone, zoom, part, time)
		]);
		const { labels, flags } = labelData;
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
				? parabolicToBody(cols as ParabolicColumns, idx, labels, flags, idMap)
				: isSGP4
					? sgp4ToBody(cols as SGP4Columns, idx, labels, flags, idMap)
					: keplerianToBody(cols as KeplerianColumns, idx, labels, flags, idMap);
			// sgp4ToBody returns null when satrec init fails — drop the row to
			// enforce SGP4-only propagation for earth sats.
			if (!body) continue;
			// If the load-time jd is outside the chunk's validity window (e.g.
			// user URL-loaded a far-future date), seed with the parent position.
			// The per-frame propagation gate keeps the body hidden until jd
			// re-enters range.
			const inRange = jd >= body.validityStart && jd <= body.validityEnd;
			// Chebyshev override: for bodies shipped with SPICE polynomials, take
			// the parent-relative offset straight from the store. Orbit curve is
			// sampled later once we know this is a rendered body (not a
			// barycenter that only acts as a reference frame).
			const chebOffset = this.cheb?.has(body.id) ? this.cheb.positionScene(body.id, jd) : null;
			const offset = chebOffset
				? chebOffset
				: !inRange
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

			// Sample the body's chebyshev trail once (Keplerian `n` gives the
			// period). Keyed by string id so planets can later borrow their parent
			// barycenter's buffer — mirroring the Keplerian `barycenters` map. The
			// `has` guard preserves already-accumulated history when the same body
			// appears in a re-processed chunk.
			if (chebOffset && body.n > 0 && !this.chebBuffers.has(body.id)) {
				const period = 360 / body.n;
				const buffer = new TrailBuffer(NUM_ORBIT_POINTS, period / NUM_ORBIT_POINTS);
				populateTrailBuffer(buffer, this.cheb!, body.id, jd);
				this.chebBuffers.set(body.id, buffer);
			}

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
					trailBuffer: this.chebBuffers.get(body.id),
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
				// Trail-buffer selection mirrors orbitElements selection: planets
				// without a barycenter entry use their own buffer; those with one
				// borrow the parent's (since the planet's own chebyshev is just
				// wobble around that barycenter).
				const parentStringId = body.parentId;
				const trailBuffer = isMoon
					? this.chebBuffers.get(body.id)
					: (this.chebBuffers.get(parentStringId) ?? this.chebBuffers.get(body.id));
				bodies.push({
					data: body,
					position: pos,
					orbitElements: isMoon ? body : (this.barycenters.get(parentId) ?? body),
					trailBuffer,
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
