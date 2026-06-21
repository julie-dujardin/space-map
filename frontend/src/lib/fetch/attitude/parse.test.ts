import { describe, it, expect } from 'vitest';
import { parseAttitudeChunk } from './parse';

const HEADER_SIZE = 16;
const KEYFRAME_SIZE = 11;
const SCALE = 32767;

/** Build an ATTI v1 buffer from (startJd, [{dt, quat:[w,x,y,z]}]) the same way
 *  the Python writer does — drop the largest-|·| component, store the rest. */
function encode(startJd: number, frames: { dt: number; q: [number, number, number, number] }[]) {
	const buf = new ArrayBuffer(HEADER_SIZE + frames.length * KEYFRAME_SIZE);
	const v = new DataView(buf);
	v.setUint8(0, 0x41); // A
	v.setUint8(1, 0x54); // T
	v.setUint8(2, 0x54); // T
	v.setUint8(3, 0x49); // I
	v.setUint16(4, 1, true);
	v.setFloat64(8, startJd, true);
	frames.forEach((f, i) => {
		const off = HEADER_SIZE + i * KEYFRAME_SIZE;
		let q = f.q;
		let idx = 0;
		for (let j = 1; j < 4; j++) if (Math.abs(q[j]) > Math.abs(q[idx])) idx = j;
		if (q[idx] < 0) q = q.map((x) => -x) as [number, number, number, number];
		const kept = [0, 1, 2, 3].filter((j) => j !== idx);
		v.setUint32(off, f.dt, true);
		v.setUint8(off + 4, idx);
		v.setInt16(off + 5, Math.round(q[kept[0]] * SCALE), true);
		v.setInt16(off + 7, Math.round(q[kept[1]] * SCALE), true);
		v.setInt16(off + 9, Math.round(q[kept[2]] * SCALE), true);
	});
	return buf;
}

describe('parseAttitudeChunk', () => {
	it('reconstructs quaternions and accumulates time', () => {
		const startJd = 2455873.5;
		const q1: [number, number, number, number] = [1, 0, 0, 0];
		// normalized (0.5, 0.5, 0.5, 0.5)
		const q2: [number, number, number, number] = [0.5, 0.5, 0.5, 0.5];
		const chunk = parseAttitudeChunk(
			encode(startJd, [
				{ dt: 0, q: q1 },
				{ dt: 86400, q: q2 }
			])
		);

		expect(chunk.times.length).toBe(2);
		expect(chunk.times[0]).toBeCloseTo(startJd, 9);
		expect(chunk.times[1]).toBeCloseTo(startJd + 1, 9); // 86400 s = 1 day

		// First keyframe round-trips exactly (w dropped, reconstructed as 1).
		expect(chunk.quats[0]).toBeCloseTo(1, 4);
		expect(chunk.quats[1]).toBeCloseTo(0, 4);
		// Second: all components |0.5|, one dropped & rebuilt via sqrt.
		for (let k = 0; k < 4; k++) expect(chunk.quats[4 + k]).toBeCloseTo(0.5, 3);

		// Every reconstructed quaternion is unit-norm.
		for (let i = 0; i < chunk.times.length; i++) {
			const b = i * 4;
			const norm = Math.hypot(...chunk.quats.slice(b, b + 4));
			expect(norm).toBeCloseTo(1, 4);
		}
	});

	it('rejects a non-ATTI buffer', () => {
		const buf = new ArrayBuffer(HEADER_SIZE);
		new DataView(buf).setUint32(0, 0x504d4153, true); // "SMAP"
		expect(() => parseAttitudeChunk(buf)).toThrow(/magic/);
	});
});
