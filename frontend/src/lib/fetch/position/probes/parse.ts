/**
 * Binary reader for the probes payload (format byte = 2).
 *
 * One file per (zone, chunk_idx). Each file aggregates every probe whose
 * coverage intersects the chunk's time window; within a probe the trajectory
 * is sliced into fixed-width sub-chunks (`subchunkDays` from the file header),
 * each independently fitted as one of:
 *   - kepler_pure   (method 1): 6 elements + 1 anchor offset
 *   - kepler_drift  (method 2): 6 elements + Ω̇,ω̇,ṅ + 1 anchor offset
 *   - chebyshev     (method 3): packed coefficients over uniform segments
 *   - uncoverable   (method 0): empty payload, consumer hides the probe
 *
 * Coefficient dtype (f32 vs f64) is NOT carried in the file header — it's a
 * zone-level property surfaced by `metadata.position.zones[zone].float64_coeffs`,
 * so the caller must pass `float64` in.
 */

import {
	HEADER_SIZE,
	IdType,
	MISSING_INT32,
	MISSING_UINT8,
	PROBE_FLAG_HAS_LANDED_RECORD,
	PROBE_HEADER_SIZE,
	PROBE_METHOD_CHEBYSHEV,
	PROBE_METHOD_KEPLER_DRIFT,
	PROBE_METHOD_KEPLER_PURE,
	PROBE_METHOD_LANDED,
	PROBE_METHOD_UNCOVERABLE,
	SUBCHUNK_HEADER_SIZE,
	SYSTEM_INTERVAL_SIZE,
	buildObjectId
} from '$lib/fetch/position/format';

const SECONDS_PER_DAY = 86400;

/** Kepler-pure / Kepler-drift element block (units match the writer). */
export interface KeplerPureElts {
	method: typeof PROBE_METHOD_KEPLER_PURE;
	aKm: number;
	e: number;
	iRad: number;
	om0: number;
	w0: number;
	m0: number;
	/** Anchor epoch as an offset (s) past the sub-chunk start ET. */
	tAnchorOffsetS: number;
}

export interface KeplerDriftElts {
	method: typeof PROBE_METHOD_KEPLER_DRIFT;
	aKm: number;
	e: number;
	iRad: number;
	om0: number;
	w0: number;
	m0: number;
	omDot: number;
	wDot: number;
	/** Fitted mean motion (rad/s) — already absorbs any J2 mean-motion drift. */
	nMeanRadS: number;
	tAnchorOffsetS: number;
}

export interface ChebyshevSub {
	method: typeof PROBE_METHOD_CHEBYSHEV;
	/** Polynomial degree + 1 per axis (fixed = 12 in the current export). */
	coeffsPerAxis: number;
	/** `nSeg = coeffs.length / (3 * coeffsPerAxis)`; segments uniformly tile the
	 *  sub-chunk window. */
	nSeg: number;
	/** Flat layout per segment: `[cx_0..cx_{N-1}, cy..., cz...]`, all f32 or all f64. */
	coeffs: Float32Array | Float64Array;
}

export interface UncoverableSub {
	method: typeof PROBE_METHOD_UNCOVERABLE;
}

export type SubChunk = KeplerPureElts | KeplerDriftElts | ChebyshevSub | UncoverableSub;

/**
 * Trailing METHOD_LANDED record — the probe is parked on a body's surface
 * during this chunk's window. Coordinates are body-fixed (IAU rotating
 * frame); the renderer applies the body's IAU orientation at eval time to
 * place the probe in world coords.
 *
 * `samples` is empty for static phases (the rover sat still in this chunk);
 * the reference position is the displayed position. For moving phases the
 * reference is the first kept sample (touchdown / chunk-start), and
 * `sampleEt` is sorted ascending. The renderer should stair-step:
 * pick the latest sample whose `et` ≤ now.
 */
export interface LandedRecord {
	bodyNaifId: number;
	isStatic: boolean;
	/** Phase entry ET (s past J2000, TDB) within or extending into this chunk. */
	startEt: number;
	/** Phase exit ET. */
	endEt: number;
	latRefDeg: number;
	lngRefDeg: number;
	altRefM: number;
	/** Per-sample absolute ET (s past J2000, TDB). Empty for static. Sorted. */
	sampleEt: Float64Array;
	sampleLatDeg: Float32Array;
	sampleLngDeg: Float32Array;
	sampleAltM: Float32Array;
}

/**
 * One "probe inside planet X's system from `startEt` to `endEt`" span,
 * attached to interplanetary records so flyby focus + visibility don't
 * need the planet zone's chunk loaded. `systemNaifId` is the barycenter
 * NAIF (Mars=4, Earth-Moon=3, …), matching `focusedSystemId`'s
 * `"naif-{n}"` form. Half-open (`t < endEt`), sorted, non-overlapping.
 */
export interface SystemInterval {
	startEt: number;
	endEt: number;
	systemNaifId: number;
}

export interface Probe {
	/** Full Object ID (`probe-<value>`), reconstructed from the header. */
	id: string;
	/** Synthetic int32 packing `inception_mjd_offset_from_1945 << 12 | dedupe`. */
	probeId: number;
	hasLocalized: boolean;
	/** ObjectType ordinal — always `spacecraft` today; surfaced for futureproofing. */
	objectType: number;
	/** Per-probe fit-center override. Null when the probe stayed on the zone's
	 *  stored fit center (renderer composes against the zone center as before).
	 *  Non-null when the writer routed this probe to a moon/asteroid — the
	 *  renderer must compose `world = fitCenter_world + probe_offset` against
	 *  this body's chebyshev state. */
	fitCenter: { id: string; idType: IdType; idValue: number } | null;
	/** Sub-chunk start ET in seconds past J2000 (TDB). */
	subStartEt: number[];
	/** Sub-chunk end ET in seconds past J2000 (TDB) — `subStartEt[i] + subchunkS`. */
	subEndEt: number[];
	subChunks: SubChunk[];
	/** Optional trailing landed record — present when the probe was on a body's
	 *  surface for part or all of this chunk. */
	landed?: LandedRecord;
	/** Planetary-system membership spans for the chunk's window. Empty on
	 *  planet-zone records (their system is the zone identity). */
	systemIntervals: SystemInterval[];
}

export interface ProbeChunk {
	/** Whole-chunk JD validity envelope (from the common header). */
	startJd: number;
	endJd: number;
	/** Sub-chunk width in days — shared across every probe in the file. */
	subchunkDays: number;
	probes: Probe[];
}

const JD_J2000 = 2451545.0;

/** Convert JD (TDB) → seconds past J2000. The probes writer stores sub-chunk
 *  boundaries implicitly via JD start of the chunk + offsets in sub-chunk
 *  units; we expand them eagerly to ET so the propagator can compute `dt`
 *  in seconds without re-doing JD arithmetic per evaluation. */
function jdToEt(jd: number): number {
	return (jd - JD_J2000) * SECONDS_PER_DAY;
}

function readFloats(
	buffer: ArrayBuffer,
	offset: number,
	count: number,
	float64: boolean
): Float32Array | Float64Array {
	const bytes = count * (float64 ? 8 : 4);
	const view = new (float64 ? Float64Array : Float32Array)(count);
	if (float64 && offset % 8 === 0) {
		view.set(new Float64Array(buffer, offset, count));
		return view;
	}
	if (!float64 && offset % 4 === 0) {
		view.set(new Float32Array(buffer, offset, count));
		return view;
	}
	// Misaligned path: walk a DataView. The sub-chunk header is 8 bytes and
	// the probe header is 12 bytes, so we can land on a 4-aligned but not
	// 8-aligned offset between probes — copy element by element instead.
	const dv = new DataView(buffer, offset, bytes);
	if (float64) {
		for (let i = 0; i < count; i++) view[i] = dv.getFloat64(i * 8, true);
	} else {
		for (let i = 0; i < count; i++) view[i] = dv.getFloat32(i * 4, true);
	}
	return view;
}

function parseKeplerPayload(
	buffer: ArrayBuffer,
	offset: number,
	method: typeof PROBE_METHOD_KEPLER_PURE | typeof PROBE_METHOD_KEPLER_DRIFT,
	float64: boolean
): KeplerPureElts | KeplerDriftElts {
	const count = method === PROBE_METHOD_KEPLER_PURE ? 7 : 10;
	const arr = readFloats(buffer, offset, count, float64);
	if (method === PROBE_METHOD_KEPLER_PURE) {
		return {
			method,
			aKm: arr[0],
			e: arr[1],
			iRad: arr[2],
			om0: arr[3],
			w0: arr[4],
			m0: arr[5],
			tAnchorOffsetS: arr[6]
		};
	}
	return {
		method,
		aKm: arr[0],
		e: arr[1],
		iRad: arr[2],
		om0: arr[3],
		w0: arr[4],
		m0: arr[5],
		omDot: arr[6],
		wDot: arr[7],
		nMeanRadS: arr[8],
		tAnchorOffsetS: arr[9]
	};
}

/**
 * METHOD_LANDED payload layout (mirrors `pack_landed_payload` in format.py):
 *
 *   0   int32   body_naif_id
 *   4   uint8   flags             (bit 0 = is_static)
 *   5   uint8[3] reserved
 *   8   uint32  start_offset_s    (from chunk_start_et)
 *   12  uint32  end_offset_s
 *   16  int32   lat_ref_e7        (lat° × 1e7)
 *   20  int32   lng_ref_e7
 *   24  int32   alt_ref_mm
 *   28  uint32  sample_count
 *   32+ sample_count × {uint32 et_offset_s, int32 lat_e7, int32 lng_e7, int32 alt_mm}
 */
const LANDED_LATLNG_SCALE = 1e-7;
const LANDED_ALT_MM_SCALE = 1e-3;
const LANDED_FLAG_STATIC = 0x01;
const LANDED_SAMPLE_SIZE = 16;
const LANDED_HEADER_SIZE = 32;

function parseLandedPayload(
	buffer: ArrayBuffer,
	offset: number,
	chunkStartEt: number
): LandedRecord {
	const view = new DataView(buffer, offset, LANDED_HEADER_SIZE);
	const bodyNaifId = view.getInt32(0, true);
	const flagsByte = view.getUint8(4);
	const startOffsetS = view.getUint32(8, true);
	const endOffsetS = view.getUint32(12, true);
	const latRefDeg = view.getInt32(16, true) * LANDED_LATLNG_SCALE;
	const lngRefDeg = view.getInt32(20, true) * LANDED_LATLNG_SCALE;
	const altRefM = view.getInt32(24, true) * LANDED_ALT_MM_SCALE;
	const sampleCount = view.getUint32(28, true);
	const sampleEt = new Float64Array(sampleCount);
	const sampleLatDeg = new Float32Array(sampleCount);
	const sampleLngDeg = new Float32Array(sampleCount);
	const sampleAltM = new Float32Array(sampleCount);
	if (sampleCount > 0) {
		const sv = new DataView(buffer, offset + LANDED_HEADER_SIZE, sampleCount * LANDED_SAMPLE_SIZE);
		for (let i = 0; i < sampleCount; i++) {
			const off = i * LANDED_SAMPLE_SIZE;
			sampleEt[i] = chunkStartEt + sv.getUint32(off, true);
			sampleLatDeg[i] = sv.getInt32(off + 4, true) * LANDED_LATLNG_SCALE;
			sampleLngDeg[i] = sv.getInt32(off + 8, true) * LANDED_LATLNG_SCALE;
			sampleAltM[i] = sv.getInt32(off + 12, true) * LANDED_ALT_MM_SCALE;
		}
	}
	return {
		bodyNaifId,
		isStatic: (flagsByte & LANDED_FLAG_STATIC) !== 0,
		startEt: chunkStartEt + startOffsetS,
		endEt: chunkStartEt + endOffsetS,
		latRefDeg,
		lngRefDeg,
		altRefM,
		sampleEt,
		sampleLatDeg,
		sampleLngDeg,
		sampleAltM
	};
}

function parseChebyshevPayload(
	buffer: ArrayBuffer,
	offset: number,
	payloadLen: number,
	float64: boolean
): ChebyshevSub {
	// Degree is fixed at 11 (12 coeffs per axis) in the current writer, but we
	// derive it from payload_len so a future change to a different degree
	// doesn't require a parser bump.
	const coeffsPerAxis = 12;
	const segBytes = 3 * coeffsPerAxis * (float64 ? 8 : 4);
	const nSeg = payloadLen / segBytes;
	const nFloats = nSeg * 3 * coeffsPerAxis;
	const coeffs = readFloats(buffer, offset, nFloats, float64);
	return { method: PROBE_METHOD_CHEBYSHEV, coeffsPerAxis, nSeg, coeffs };
}

export function parseProbesPayload(
	buffer: ArrayBuffer,
	startJd: number,
	endJd: number,
	float64Coeffs: boolean
): ProbeChunk {
	const view = new DataView(buffer);
	const probeCount = view.getUint32(24, true);
	const subchunkDays = view.getFloat32(28, true);
	const subchunkS = subchunkDays * SECONDS_PER_DAY;
	const chunkStartEt = jdToEt(startJd);

	const probes: Probe[] = [];
	let offset = HEADER_SIZE;

	for (let p = 0; p < probeCount; p++) {
		const objIdValue = view.getInt32(offset, true);
		const idTypeOrdinal = view.getUint8(offset + 4) as IdType;
		const objectType = view.getUint8(offset + 5);
		const hasLocalized = view.getUint8(offset + 6) === 1;
		const flags = view.getUint8(offset + 7);
		const hasLandedRecord = (flags & PROBE_FLAG_HAS_LANDED_RECORD) !== 0;
		const nSubchunks = view.getUint16(offset + 8, true);
		const firstSubchunkOffset = view.getUint16(offset + 10, true);
		const fitCenterIdValue = view.getInt32(offset + 12, true);
		const fitCenterIdType = view.getUint8(offset + 16);
		const nSystemIntervals = view.getUint8(offset + 17);
		offset += PROBE_HEADER_SIZE;

		const id = buildObjectId(idTypeOrdinal, objIdValue) ?? '';
		if (!id) {
			console.warn(
				`probes payload: probe[${p}] (value=${objIdValue}) has unknown id-type ${idTypeOrdinal}; skipping`
			);
		}

		let fitCenter: Probe['fitCenter'] = null;
		if (fitCenterIdValue !== MISSING_INT32 && fitCenterIdType !== MISSING_UINT8) {
			const fcId = buildObjectId(fitCenterIdType, fitCenterIdValue);
			if (fcId) {
				fitCenter = { id: fcId, idType: fitCenterIdType as IdType, idValue: fitCenterIdValue };
			} else {
				console.warn(
					`probes payload: probe[${p}] has unknown fit-center id-type ${fitCenterIdType}; falling back to zone default`
				);
			}
		}

		const subStartEt: number[] = new Array(nSubchunks);
		const subEndEt: number[] = new Array(nSubchunks);
		const subChunks: SubChunk[] = new Array(nSubchunks);

		for (let s = 0; s < nSubchunks; s++) {
			const method = view.getUint8(offset);
			// 1 reserved + 2 reserved2
			const payloadLen = view.getUint32(offset + 4, true);
			const payloadOffset = offset + SUBCHUNK_HEADER_SIZE;
			const subStart = chunkStartEt + (firstSubchunkOffset + s) * subchunkS;
			subStartEt[s] = subStart;
			subEndEt[s] = subStart + subchunkS;
			if (method === PROBE_METHOD_UNCOVERABLE) {
				subChunks[s] = { method: PROBE_METHOD_UNCOVERABLE };
			} else if (method === PROBE_METHOD_KEPLER_PURE || method === PROBE_METHOD_KEPLER_DRIFT) {
				subChunks[s] = parseKeplerPayload(buffer, payloadOffset, method, float64Coeffs);
			} else if (method === PROBE_METHOD_CHEBYSHEV) {
				subChunks[s] = parseChebyshevPayload(buffer, payloadOffset, payloadLen, float64Coeffs);
			} else {
				throw new Error(`Unknown probe sub-chunk method ${method} at probe ${p} sub ${s}`);
			}
			offset = payloadOffset + payloadLen;
		}

		// Trailing METHOD_LANDED record — the probe is parked on a body's
		// surface for part or all of this chunk. The renderer applies the
		// body's IAU orientation at eval time to place the probe in world
		// coords (no trail — landed probes aren't on an orbit).
		let landed: LandedRecord | undefined;
		if (hasLandedRecord) {
			const method = view.getUint8(offset);
			if (method !== PROBE_METHOD_LANDED) {
				throw new Error(
					`probe ${p}: PROBE_FLAG_HAS_LANDED_RECORD set but trailing record method = ${method}, expected ${PROBE_METHOD_LANDED}`
				);
			}
			const payloadLen = view.getUint32(offset + 4, true);
			const po = offset + SUBCHUNK_HEADER_SIZE;
			landed = parseLandedPayload(buffer, po, chunkStartEt);
			offset = po + payloadLen;
		}

		const systemIntervals: SystemInterval[] = new Array(nSystemIntervals);
		for (let k = 0; k < nSystemIntervals; k++) {
			systemIntervals[k] = {
				startEt: view.getFloat64(offset, true),
				endEt: view.getFloat64(offset + 8, true),
				systemNaifId: view.getUint8(offset + 16)
			};
			offset += SYSTEM_INTERVAL_SIZE;
		}

		probes.push({
			id,
			probeId: objIdValue,
			hasLocalized,
			objectType,
			fitCenter,
			subStartEt,
			subEndEt,
			subChunks,
			landed,
			systemIntervals
		});
	}

	return { startJd, endJd, subchunkDays, probes };
}
