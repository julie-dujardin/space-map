/**
 * Binary reader for elements.bin — the columnar orbital elements file.
 * Creates zero-copy typed array views over the fetched ArrayBuffer.
 */

import { MAGIC, VERSION, HEADER_SIZE } from './format';

export interface ElementColumns {
	eid: Int32Array;
	objectType: Uint8Array;
	naifId: Int32Array;
	parentNaifId: Int32Array;
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

/** Round up to next multiple of 8. */
function align8(n: number): number {
	return (n + 7) & ~7;
}

export async function fetchElements(url = '/data/v1/elements.bin'): Promise<ElementColumns> {
	const res = await fetch(url);
	if (!res.ok) throw new Error(`Failed to fetch elements: ${res.status}`);
	const buffer = await res.arrayBuffer();
	return parseElements(buffer);
}

export function parseElements(buffer: ArrayBuffer): ElementColumns {
	const view = new DataView(buffer);

	// Parse header
	const magic = view.getUint32(0, true);
	if (magic !== MAGIC) {
		throw new Error(`Invalid elements file: bad magic 0x${magic.toString(16)}`);
	}
	const version = view.getUint16(4, true);
	if (version !== VERSION) {
		throw new Error(`Unsupported elements version: ${version}`);
	}
	const rowCount = view.getUint32(8, true);

	let offset = HEADER_SIZE;

	// Column 0: eid (int32)
	const eid = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Column 1: object_type (uint8)
	const objectType = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);

	// Column 2: naif_id (int32)
	const naifId = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Column 3: parent_naif_id (int32)
	const parentNaifId = new Int32Array(buffer, offset, rowCount);
	offset += align8(rowCount * 4);

	// Column 4: scale (uint8)
	const scale = new Uint8Array(buffer, offset, rowCount);
	offset += align8(rowCount);

	// Columns 5–13: float64
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
		eid,
		objectType,
		naifId,
		parentNaifId,
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
