/**
 * Binary reader for elements.bin — the columnar orbital elements file.
 * Creates zero-copy typed array views over the fetched ArrayBuffer.
 */

import {
	MAGIC,
	VERSION,
	HEADER_SIZE,
	FORMAT_KEPLERIAN,
	FORMAT_PARABOLIC,
	FORMAT_SGP4,
	OrbitalSource,
	elementsBinUrl
} from '$lib/fetch/elements/constants';

/**
 * Chunk-level validity window (JD TDB). Propagation is only defined inside
 * `[validityStart, validityEnd]`; consumers hide bodies whose current `jd` is
 * outside the window. `-Infinity`/`+Infinity` means unbounded — Keplerian/
 * parabolic orbits have no hard cutoff, so exporters leave them unbounded.
 */
export interface Validity {
	validityStart: number;
	validityEnd: number;
}

/**
 * Chunk-level metadata shared by every row in the file — validity window plus
 * the provider that produced the elements.
 */
export interface ChunkMeta extends Validity {
	source: OrbitalSource;
}

export interface KeplerianColumns extends ChunkMeta {
	kind: 'keplerian';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	a: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	ma: Float32Array;
	n: Float32Array;
	radiusKm: Float32Array;
	rowCount: number;
}

export interface ParabolicColumns extends ChunkMeta {
	kind: 'parabolic';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	q: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	tp: Float64Array;
	radiusKm: Float32Array;
	rowCount: number;
}

/**
 * SGP4 columns — superset of Keplerian with the extra OMM fields that
 * satellite.js `json2satrec` needs. Raw OMM units: `a` in km, `n` in rev/day,
 * angles in degrees, BSTAR in 1/Earth radii, n-dot in rev/day², n-ddot in rev/day³.
 */
export interface SGP4Columns extends ChunkMeta {
	kind: 'sgp4';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	a: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	ma: Float32Array;
	n: Float32Array;
	radiusKm: Float32Array;
	bstar: Float32Array;
	meanMotionDot: Float32Array;
	meanMotionDdot: Float32Array;
	elementSetNo: Int32Array;
	revAtEpoch: Int32Array;
	rowCount: number;
}

export type ElementColumns = KeplerianColumns | ParabolicColumns | SGP4Columns;

/** Round up to next multiple of 8. */
function align8(n: number): number {
	return (n + 7) & ~7;
}

export async function fetchElements(
	zone: string,
	zoom: number,
	part: number,
	time: string | null = null
): Promise<ElementColumns> {
	const res = await fetch(elementsBinUrl(zone, zoom, part, time));
	if (!res.ok) throw new Error(`Failed to fetch elements: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	const buffer = await new Response(res.body!.pipeThrough(ds)).arrayBuffer();
	return parseElements(buffer);
}

/** Parse header fields shared by all format types. */
function parseHeader(buffer: ArrayBuffer): { formatType: number; rowCount: number } & ChunkMeta {
	const view = new DataView(buffer);
	const magic = view.getUint32(0, true);
	if (magic !== MAGIC) {
		throw new Error(`Invalid elements file: bad magic 0x${magic.toString(16)}`);
	}
	const version = view.getUint16(4, true);
	if (version !== VERSION) {
		throw new Error(`Unsupported elements version: ${version}`);
	}
	return {
		formatType: view.getUint16(6, true),
		validityStart: view.getFloat64(8, true),
		validityEnd: view.getFloat64(16, true),
		rowCount: view.getUint32(24, true),
		source: view.getUint8(28) as OrbitalSource
	};
}

/** Parse shared columns 0–3 (id, objectType, parentId, scale). */
function parseSharedColumns(
	buffer: ArrayBuffer,
	rowCount: number
): {
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	offset: number;
} {
	let offset = HEADER_SIZE;

	const id = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	const objectType = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);

	const parentId = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	const scale = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);

	return { id, objectType, parentId, scale, offset };
}

/** Parse the common Keplerian columns 4–12. Returns the columns plus the next byte offset. */
function parseKeplerianColumns(
	buffer: ArrayBuffer,
	rowCount: number,
	startOffset: number
): {
	epochJd: Float64Array;
	a: Float32Array;
	e: Float32Array;
	i: Float32Array;
	om: Float32Array;
	w: Float32Array;
	ma: Float32Array;
	n: Float32Array;
	radiusKm: Float32Array;
	offset: number;
} {
	let offset = startOffset;

	// Column 4: epoch_jd (float64 — Julian Dates need full precision)
	const epochJd = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;

	// Columns 5–11: float32 orbital elements
	const a = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const e = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const i = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const om = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const w = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const ma = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const n = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Column 12: radius_km (float32)
	const radiusKm = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	return { epochJd, a, e, i, om, w, ma, n, radiusKm, offset };
}

export function parseElements(buffer: ArrayBuffer): ElementColumns {
	const { formatType, rowCount, validityStart, validityEnd, source } = parseHeader(buffer);
	const meta: ChunkMeta = { validityStart, validityEnd, source };

	if (formatType === FORMAT_PARABOLIC) {
		return parseParabolicElements(buffer, rowCount, meta);
	}
	if (formatType === FORMAT_SGP4) {
		return parseSGP4Elements(buffer, rowCount, meta);
	}
	if (formatType !== FORMAT_KEPLERIAN) {
		throw new Error(`Unknown elements format type: ${formatType}`);
	}

	const { id, objectType, parentId, scale, offset } = parseSharedColumns(buffer, rowCount);
	const kepler = parseKeplerianColumns(buffer, rowCount, offset);

	return {
		kind: 'keplerian',
		id,
		objectType,
		parentId,
		scale,
		epochJd: kepler.epochJd,
		a: kepler.a,
		e: kepler.e,
		i: kepler.i,
		om: kepler.om,
		w: kepler.w,
		ma: kepler.ma,
		n: kepler.n,
		radiusKm: kepler.radiusKm,
		rowCount,
		...meta
	};
}

function parseSGP4Elements(buffer: ArrayBuffer, rowCount: number, meta: ChunkMeta): SGP4Columns {
	const {
		id,
		objectType,
		parentId,
		scale,
		offset: sharedEnd
	} = parseSharedColumns(buffer, rowCount);
	const kepler = parseKeplerianColumns(buffer, rowCount, sharedEnd);
	let offset = kepler.offset;

	// Columns 13–15: bstar, mean_motion_dot, mean_motion_ddot (float32)
	const bstar = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const meanMotionDot = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const meanMotionDdot = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Columns 16–17: element_set_no, rev_at_epoch (int32)
	const elementSetNo = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const revAtEpoch = new Int32Array(buffer, offset, rowCount);

	return {
		kind: 'sgp4',
		id,
		objectType,
		parentId,
		scale,
		epochJd: kepler.epochJd,
		a: kepler.a,
		e: kepler.e,
		i: kepler.i,
		om: kepler.om,
		w: kepler.w,
		ma: kepler.ma,
		n: kepler.n,
		radiusKm: kepler.radiusKm,
		bstar,
		meanMotionDot,
		meanMotionDdot,
		elementSetNo,
		revAtEpoch,
		rowCount,
		...meta
	};
}

function parseParabolicElements(
	buffer: ArrayBuffer,
	rowCount: number,
	meta: ChunkMeta
): ParabolicColumns {
	const {
		id,
		objectType,
		parentId,
		scale,
		offset: startOffset
	} = parseSharedColumns(buffer, rowCount);
	let offset = startOffset;

	// Column 4: epoch_jd (float64 — Julian Dates need full precision)
	const epochJd = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;

	// Column 5: q (float32, perihelion distance AU)
	const q = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Columns 6–9: e, i, om, w (float32)
	const e = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const i = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const om = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);
	const w = new Float32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Column 10: tp (float64 — Julian Dates need full precision)
	const tp = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;

	// Column 11: radius_km (float32)
	const radiusKm = new Float32Array(buffer, offset, rowCount);

	return {
		kind: 'parabolic',
		id,
		objectType,
		parentId,
		scale,
		epochJd,
		q,
		e,
		i,
		om,
		w,
		tp,
		radiusKm,
		rowCount,
		...meta
	};
}
