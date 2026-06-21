/**
 * Binary reader for probe-attitude chunks (`v1/attitude/{id}/{N}.bin.gz`).
 * Header carries the start JD; keyframes are dt-delta-encoded smallest-three
 * quaternions. Mirrors the writer in `.../attitude/format.py` (magic `ATTI`, v1).
 */

const MAGIC = 0x49545441; // "ATTI" little-endian (bytes A,T,T,I)
const VERSION = 1;
const HEADER_SIZE = 16;
const KEYFRAME_SIZE = 11;
const COMPONENT_SCALE = 32767;
const SECONDS_PER_DAY = 86400;

/** Decoded chunk: per-keyframe absolute JD plus unit quaternions (w,x,y,z),
 *  flattened `4 · n`. Quaternions are residuals when the manifest carries a
 *  spin baseline, raw body-frame orientation otherwise. */
export interface AttitudeChunk {
	/** Absolute JD (TDB) per keyframe, ascending. */
	times: Float64Array;
	/** `[w0,x0,y0,z0, w1,...]` — unit, smallest-three reconstructed. */
	quats: Float32Array;
}

/**
 * Decode one already-gunzipped ATTI buffer. Throws on a bad magic/version so a
 * misrouted (e.g. position `SMAP`) file can't be silently misread.
 */
export function parseAttitudeChunk(buffer: ArrayBuffer): AttitudeChunk {
	const view = new DataView(buffer);
	if (view.getUint32(0, true) !== MAGIC) {
		throw new Error('attitude: bad file magic (expected ATTI)');
	}
	const version = view.getUint16(4, true);
	if (version !== VERSION) {
		throw new Error(`attitude: unsupported version ${version}`);
	}
	const startJd = view.getFloat64(8, true);

	const n = Math.floor((buffer.byteLength - HEADER_SIZE) / KEYFRAME_SIZE);
	const times = new Float64Array(n);
	const quats = new Float32Array(n * 4);

	let cursorSeconds = 0;
	for (let i = 0; i < n; i++) {
		const off = HEADER_SIZE + i * KEYFRAME_SIZE;
		// First keyframe's dt is 0 by construction; accumulate the rest.
		if (i > 0) cursorSeconds += view.getUint32(off, true);
		times[i] = startJd + cursorSeconds / SECONDS_PER_DAY;

		const idx = view.getUint8(off + 4);
		const a = view.getInt16(off + 5, true) / COMPONENT_SCALE;
		const b = view.getInt16(off + 7, true) / COMPONENT_SCALE;
		const c = view.getInt16(off + 9, true) / COMPONENT_SCALE;
		// Smallest-three: the dropped (largest-|·|) component is reconstructed
		// non-negative — the writer flips sign so the sqrt is unambiguous.
		const dropped = Math.sqrt(Math.max(0, 1 - a * a - b * b - c * c));

		const base = i * 4;
		let k = 0;
		for (let slot = 0; slot < 4; slot++) {
			if (slot === idx) {
				quats[base + slot] = dropped;
			} else {
				quats[base + slot] = k === 0 ? a : k === 1 ? b : c;
				k++;
			}
		}
	}
	return { times, quats };
}
