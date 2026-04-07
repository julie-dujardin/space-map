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
	elementsBinUrl
} from '$lib/fetch/elements/constants';

export interface KeplerianColumns {
	kind: 'keplerian';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	a: Float64Array;
	e: Float64Array;
	i: Float64Array;
	om: Float64Array;
	w: Float64Array;
	ma: Float64Array;
	n: Float64Array;
	radiusKm: Float64Array;
	rowCount: number;
}

export interface ParabolicColumns {
	kind: 'parabolic';
	id: Int32Array;
	objectType: Uint8Array;
	parentId: Int32Array;
	scale: Uint8Array;
	epochJd: Float64Array;
	q: Float64Array;
	e: Float64Array;
	i: Float64Array;
	om: Float64Array;
	w: Float64Array;
	tp: Float64Array;
	radiusKm: Float64Array;
	rowCount: number;
}

export type ElementColumns = KeplerianColumns | ParabolicColumns;

/** Round up to next multiple of 8. */
function align8(n: number): number {
	return (n + 7) & ~7;
}

export async function fetchElements(
	zone: string,
	zoom: number,
	part: number
): Promise<ElementColumns> {
	const res = await fetch(elementsBinUrl(zone, zoom, part));
	if (!res.ok) throw new Error(`Failed to fetch elements: ${res.status}`);
	const ds = new DecompressionStream('gzip');
	const buffer = await new Response(res.body!.pipeThrough(ds)).arrayBuffer();
	return parseElements(buffer);
}

/** Parse header fields shared by all format types. */
function parseHeader(buffer: ArrayBuffer): { formatType: number; rowCount: number } {
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
		rowCount: view.getUint32(8, true)
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

export function parseElements(buffer: ArrayBuffer): ElementColumns {
	const { formatType, rowCount } = parseHeader(buffer);

	if (formatType === FORMAT_PARABOLIC) {
		return parseParabolicElements(buffer, rowCount);
	}
	if (formatType !== FORMAT_KEPLERIAN) {
		throw new Error(`Unknown elements format type: ${formatType}`);
	}

	const {
		id,
		objectType,
		parentId,
		scale,
		offset: startOffset
	} = parseSharedColumns(buffer, rowCount);
	let offset = startOffset;

	// Columns 4–11: Keplerian float64
	const epochJd = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const a = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const e = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const i = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const om = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const w = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const ma = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const n = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const radiusKm = new Float64Array(buffer, offset, rowCount);

	return {
		kind: 'keplerian',
		id,
		objectType,
		parentId,
		scale,
		epochJd,
		a,
		e,
		i,
		om,
		w,
		ma,
		n,
		radiusKm,
		rowCount
	};
}

function parseParabolicElements(buffer: ArrayBuffer, rowCount: number): ParabolicColumns {
	const {
		id,
		objectType,
		parentId,
		scale,
		offset: startOffset
	} = parseSharedColumns(buffer, rowCount);
	let offset = startOffset;

	// Columns 4–10: parabolic float64 (epoch_jd, q, e, i, om, w, tp)
	const epochJd = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const q = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const e = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const i = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const om = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const w = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const tp = new Float64Array(buffer, offset, rowCount);
	offset += rowCount * 8;
	const radiusKm = new Float64Array(buffer, offset, rowCount);

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
		rowCount
	};
}
