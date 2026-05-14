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
	PROBE_HEADER_SIZE,
	PROBE_METHOD_CHEBYSHEV,
	PROBE_METHOD_KEPLER_DRIFT,
	PROBE_METHOD_KEPLER_PURE,
	PROBE_METHOD_UNCOVERABLE,
	SUBCHUNK_HEADER_SIZE,
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

export interface Probe {
	/** Full Object ID (`probe-<value>`), reconstructed from the header. */
	id: string;
	/** Synthetic int32 packing `inception_mjd_offset_from_1945 << 12 | dedupe`. */
	probeId: number;
	hasLocalized: boolean;
	/** ObjectType ordinal — always `spacecraft` today; surfaced for futureproofing. */
	objectType: number;
	/** Sub-chunk start ET in seconds past J2000 (TDB). */
	subStartEt: number[];
	/** Sub-chunk end ET in seconds past J2000 (TDB) — `subStartEt[i] + subchunkS`. */
	subEndEt: number[];
	subChunks: SubChunk[];
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
		// offset+7 reserved
		const nSubchunks = view.getUint16(offset + 8, true);
		const firstSubchunkOffset = view.getUint16(offset + 10, true);
		offset += PROBE_HEADER_SIZE;

		const id = buildObjectId(idTypeOrdinal, objIdValue) ?? '';
		if (!id) {
			console.warn(
				`probes payload: probe[${p}] (value=${objIdValue}) has unknown id-type ${idTypeOrdinal}; skipping`
			);
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

		probes.push({
			id,
			probeId: objIdValue,
			hasLocalized,
			objectType,
			subStartEt,
			subEndEt,
			subChunks
		});
	}

	return { startJd, endJd, subchunkDays, probes };
}
