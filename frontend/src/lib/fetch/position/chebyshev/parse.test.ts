import { describe, it, expect } from 'vitest';
import { parseChebyshevPayload } from './parse';
import { chebyshevPositionKm } from './propagate';
import {
	CHEBYSHEV_BODY_HEADER_SIZE,
	FORMAT_CHEBYSHEV,
	HEADER_SIZE,
	IdType,
	MAGIC,
	VERSION
} from '$lib/fetch/position/format';

interface SegmentSpec {
	startJd: number;
	endJd: number;
	cx: number[];
	cy: number[];
	cz: number[];
}

interface BodySpec {
	naifId: number;
	parentId: number;
	objIdValue: number;
	idType: IdType;
	radiusKm: number;
	coeffsPerAxis: number;
	segments: SegmentSpec[];
}

/**
 * Build a chebyshev-payload position file. The 32-byte unified header is
 * common(24) + chebyshev extension(8 = body_count + reserved); each body
 * record uses the v7 layout where segment_count shrank to uint16 to make
 * room for object_type and a reserved byte.
 */
function buildBuffer(chunkStart: number, chunkEnd: number, bodies: BodySpec[]): ArrayBuffer {
	let size = HEADER_SIZE;
	for (const b of bodies) {
		size += CHEBYSHEV_BODY_HEADER_SIZE;
		size += b.segments.length * (16 + 12 * b.coeffsPerAxis);
	}
	const buf = new ArrayBuffer(size);
	const view = new DataView(buf);
	view.setUint32(0, MAGIC, true);
	view.setUint16(4, VERSION, true);
	view.setUint8(6, FORMAT_CHEBYSHEV);
	view.setUint8(7, 0);
	view.setFloat64(8, chunkStart, true);
	view.setFloat64(16, chunkEnd, true);
	view.setUint32(24, bodies.length, true); // body_count
	view.setUint32(28, 0, true); // reserved

	let off = HEADER_SIZE;
	for (const b of bodies) {
		view.setInt32(off, b.naifId, true);
		view.setInt32(off + 4, b.parentId, true);
		view.setInt32(off + 8, b.objIdValue, true);
		view.setFloat32(off + 12, b.radiusKm, true);
		view.setUint16(off + 16, b.coeffsPerAxis, true);
		view.setUint8(off + 18, b.idType);
		view.setUint8(off + 19, 0); // has_localized
		view.setUint8(off + 20, 0); // object_type
		view.setUint8(off + 21, 0); // reserved
		view.setUint16(off + 22, b.segments.length, true); // segment_count (uint16)
		off += CHEBYSHEV_BODY_HEADER_SIZE;
		for (const seg of b.segments) {
			view.setFloat64(off, seg.startJd, true);
			view.setFloat64(off + 8, seg.endJd, true);
			off += 16;
			for (let i = 0; i < b.coeffsPerAxis; i++) view.setFloat32(off + i * 4, seg.cx[i], true);
			off += 4 * b.coeffsPerAxis;
			for (let i = 0; i < b.coeffsPerAxis; i++) view.setFloat32(off + i * 4, seg.cy[i], true);
			off += 4 * b.coeffsPerAxis;
			for (let i = 0; i < b.coeffsPerAxis; i++) view.setFloat32(off + i * 4, seg.cz[i], true);
			off += 4 * b.coeffsPerAxis;
		}
	}
	return buf;
}

function parse(buf: ArrayBuffer) {
	return parseChebyshevPayload(
		buf,
		new DataView(buf).getFloat64(8, true),
		new DataView(buf).getFloat64(16, true)
	);
}

describe('parseChebyshevPayload — synthetic buffers', () => {
	it('parses header and body metadata', () => {
		const buf = buildBuffer(100, 200, [
			{
				naifId: 399,
				parentId: 3,
				objIdValue: 399,
				idType: IdType.NAIF,
				radiusKm: 6378.137,
				coeffsPerAxis: 3,
				segments: [{ startJd: 100, endJd: 150, cx: [1, 0, 0], cy: [0, 1, 0], cz: [0, 0, 1] }]
			}
		]);
		const chunk = parse(buf);
		expect(chunk.startJd).toBe(100);
		expect(chunk.endJd).toBe(200);
		expect(chunk.bodies).toHaveLength(1);
		const body = chunk.bodies[0];
		expect(body.id).toBe('naif-399');
		expect(body.naifId).toBe(399);
		expect(body.parentId).toBe(3);
		expect(body.radiusKm).toBeCloseTo(6378.137, 2);
		expect(body.coeffsPerAxis).toBe(3);
		expect(body.startJds).toEqual(new Float64Array([100]));
		expect(body.endJds).toEqual(new Float64Array([150]));
	});

	it('reconstructs spkid IDs even when the SPICE naif_id differs', () => {
		// Pluto in chebyshev: SPICE naif_id 999, but Object.id is `spkid-20134340`.
		const buf = buildBuffer(100, 200, [
			{
				naifId: 999,
				parentId: 9,
				objIdValue: 20134340,
				idType: IdType.SPKID,
				radiusKm: 1188.3,
				coeffsPerAxis: 2,
				segments: [{ startJd: 100, endJd: 200, cx: [1, 0], cy: [0, 1], cz: [0, 0] }]
			}
		]);
		const body = parse(buf).bodies[0];
		expect(body.id).toBe('spkid-20134340');
		expect(body.naifId).toBe(999);
	});

	it('walks multiple bodies and multiple segments without drift', () => {
		const buf = buildBuffer(100, 200, [
			{
				naifId: 1,
				parentId: 0,
				objIdValue: 1,
				idType: IdType.NAIF,
				radiusKm: NaN,
				coeffsPerAxis: 2,
				segments: [
					{ startJd: 100, endJd: 150, cx: [1, 2], cy: [3, 4], cz: [5, 6] },
					{ startJd: 150, endJd: 200, cx: [7, 8], cy: [9, 10], cz: [11, 12] }
				]
			},
			{
				naifId: 2,
				parentId: 0,
				objIdValue: 2,
				idType: IdType.NAIF,
				radiusKm: 100.0,
				coeffsPerAxis: 4,
				segments: [
					{
						startJd: 110,
						endJd: 190,
						cx: [1, 0, 0, 0],
						cy: [0, 1, 0, 0],
						cz: [0, 0, 1, 0]
					}
				]
			}
		]);
		const chunk = parse(buf);
		expect(chunk.bodies).toHaveLength(2);

		const b1 = chunk.bodies[0];
		expect(b1.coeffs).toEqual(new Float32Array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]));

		const b2 = chunk.bodies[1];
		expect(b2.id).toBe('naif-2');
		expect(b2.naifId).toBe(2);
		expect(b2.coeffsPerAxis).toBe(4);
		expect(b2.radiusKm).toBeCloseTo(100.0, 5);
		expect(b2.coeffs).toEqual(new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]));
	});
});

describe('chebyshevPositionKm — Chebyshev evaluation', () => {
	// T_0(τ)=1, T_1(τ)=τ, T_2(τ)=2τ²-1 give known values at τ ∈ {-1, 0, 1}.
	// With coeffs [c0,c1,c2]: τ=1 → c0+c1+c2; τ=-1 → c0-c1+c2; τ=0 → c0-c2.
	const buf = buildBuffer(0, 10, [
		{
			naifId: 1,
			parentId: 0,
			objIdValue: 1,
			idType: IdType.NAIF,
			radiusKm: NaN,
			coeffsPerAxis: 3,
			segments: [
				{ startJd: 0, endJd: 2, cx: [1, 2, 3], cy: [0, 0, 0], cz: [10, 0, 0] },
				{ startJd: 2, endJd: 4, cx: [5, 0, 0], cy: [0, 1, 0], cz: [0, 0, 1] }
			]
		}
	]);
	const body = parse(buf).bodies[0];

	it('returns null when jd is before the covered range', () => {
		expect(chebyshevPositionKm(body, -1)).toBeNull();
	});

	it('returns null when jd is at or past the covered range end', () => {
		expect(chebyshevPositionKm(body, 4)).toBeNull();
		expect(chebyshevPositionKm(body, 10)).toBeNull();
	});

	it('evaluates at τ=-1 (segment start) correctly', () => {
		const p = chebyshevPositionKm(body, 0);
		expect(p).not.toBeNull();
		// τ=-1 on seg 0: x = 1-2+3 = 2, y=0, z=10
		expect(p![0]).toBeCloseTo(2, 5);
		expect(p![1]).toBeCloseTo(0, 5);
		expect(p![2]).toBeCloseTo(10, 5);
	});

	it('evaluates at τ=0 (segment midpoint) correctly', () => {
		const p = chebyshevPositionKm(body, 1);
		expect(p).not.toBeNull();
		// τ=0 on seg 0: x = 1-3 = -2, y=0, z=10
		expect(p![0]).toBeCloseTo(-2, 5);
		expect(p![1]).toBeCloseTo(0, 5);
		expect(p![2]).toBeCloseTo(10, 5);
	});

	it('picks the correct segment across the boundary', () => {
		// JD=2 is the start of seg 1, so τ=-1 on seg 1:
		// x = 5-0+0 = 5, y = 0-1+0 = -1, z = 0-0+1 = 1
		const p = chebyshevPositionKm(body, 2);
		expect(p).not.toBeNull();
		expect(p![0]).toBeCloseTo(5, 5);
		expect(p![1]).toBeCloseTo(-1, 5);
		expect(p![2]).toBeCloseTo(1, 5);
	});

	it('handles a single-coefficient (constant) polynomial', () => {
		const constBuf = buildBuffer(0, 10, [
			{
				naifId: 1,
				parentId: 0,
				objIdValue: 1,
				idType: IdType.NAIF,
				radiusKm: NaN,
				coeffsPerAxis: 1,
				segments: [{ startJd: 0, endJd: 10, cx: [42], cy: [-7], cz: [3] }]
			}
		]);
		const b = parse(constBuf).bodies[0];
		const p = chebyshevPositionKm(b, 5);
		expect(p).toEqual([42, -7, 3]);
	});
});
