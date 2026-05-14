import { describe, expect, it } from 'vitest';
import { parseProbesPayload } from './parse';
import { probePositionKm } from './propagate';
import {
	FORMAT_PROBES,
	HEADER_SIZE,
	IdType,
	MAGIC,
	PROBE_HEADER_SIZE,
	PROBE_METHOD_CHEBYSHEV,
	PROBE_METHOD_KEPLER_DRIFT,
	PROBE_METHOD_KEPLER_PURE,
	PROBE_METHOD_UNCOVERABLE,
	SUBCHUNK_HEADER_SIZE,
	VERSION
} from '$lib/fetch/position/format';

interface SubChunkSpec {
	method: number;
	payload: number[];
}

interface ProbeSpec {
	probeId: number;
	objectType: number;
	hasLocalized: boolean;
	firstSubchunkOffset: number;
	subChunks: SubChunkSpec[];
}

function buildBuffer(
	startJd: number,
	endJd: number,
	subchunkDays: number,
	probes: ProbeSpec[],
	float64: boolean
): ArrayBuffer {
	const coeffBytes = float64 ? 8 : 4;
	let size = HEADER_SIZE;
	for (const p of probes) {
		size += PROBE_HEADER_SIZE;
		for (const sc of p.subChunks) {
			size += SUBCHUNK_HEADER_SIZE + sc.payload.length * coeffBytes;
		}
	}
	const buf = new ArrayBuffer(size);
	const view = new DataView(buf);
	view.setUint32(0, MAGIC, true);
	view.setUint16(4, VERSION, true);
	view.setUint8(6, FORMAT_PROBES);
	view.setUint8(7, 0);
	view.setFloat64(8, startJd, true);
	view.setFloat64(16, endJd, true);
	view.setUint32(24, probes.length, true);
	view.setFloat32(28, subchunkDays, true);

	let off = HEADER_SIZE;
	for (const p of probes) {
		view.setInt32(off, p.probeId, true);
		view.setUint8(off + 4, IdType.PROBE);
		view.setUint8(off + 5, p.objectType);
		view.setUint8(off + 6, p.hasLocalized ? 1 : 0);
		view.setUint8(off + 7, 0);
		view.setUint16(off + 8, p.subChunks.length, true);
		view.setUint16(off + 10, p.firstSubchunkOffset, true);
		off += PROBE_HEADER_SIZE;
		for (const sc of p.subChunks) {
			const payloadLen = sc.payload.length * coeffBytes;
			view.setUint8(off, sc.method);
			view.setUint8(off + 1, 0);
			view.setUint16(off + 2, 0, true);
			view.setUint32(off + 4, payloadLen, true);
			off += SUBCHUNK_HEADER_SIZE;
			for (let i = 0; i < sc.payload.length; i++) {
				if (float64) view.setFloat64(off + i * 8, sc.payload[i], true);
				else view.setFloat32(off + i * 4, sc.payload[i], true);
			}
			off += payloadLen;
		}
	}
	return buf;
}

describe('parseProbesPayload — synthetic buffers', () => {
	it('reads probe header + subchunk_days + chunk window', () => {
		const buf = buildBuffer(
			2451545.0,
			2451545.0 + 7.0,
			7.0,
			[
				{
					probeId: 0xdeadbeef >> 0,
					objectType: 13,
					hasLocalized: true,
					firstSubchunkOffset: 0,
					subChunks: [{ method: PROBE_METHOD_UNCOVERABLE, payload: [] }]
				}
			],
			false
		);
		const chunk = parseProbesPayload(buf, 2451545.0, 2451545.0 + 7.0, false);
		expect(chunk.startJd).toBe(2451545.0);
		expect(chunk.endJd).toBeCloseTo(2451552.0, 9);
		expect(chunk.subchunkDays).toBeCloseTo(7.0, 5);
		expect(chunk.probes).toHaveLength(1);
		const probe = chunk.probes[0];
		expect(probe.id).toBe(`probe-${probe.probeId}`);
		expect(probe.hasLocalized).toBe(true);
		expect(probe.objectType).toBe(13);
		expect(probe.subChunks[0].method).toBe(PROBE_METHOD_UNCOVERABLE);
	});

	it('parses a kepler_pure sub-chunk and propagates it', () => {
		// Circular orbit at a=10000 km with mu=3.986e5 (Earth's GM): period ≈ 9952 s.
		// Pick t_anchor = sub_start (offset 0), m0 = 0. At et = t_anchor the probe
		// should be at (a, 0, 0) in the orbital plane (i=om=w=0).
		const aKm = 10000;
		const buf = buildBuffer(
			2451545.0,
			2451545.0 + 1.0,
			1.0,
			[
				{
					probeId: 1,
					objectType: 13,
					hasLocalized: false,
					firstSubchunkOffset: 0,
					subChunks: [
						{
							method: PROBE_METHOD_KEPLER_PURE,
							payload: [aKm, 0, 0, 0, 0, 0, 0] // a, e, i, om, w, m0, t_anchor_offset
						}
					]
				}
			],
			false
		);
		const chunk = parseProbesPayload(buf, 2451545.0, 2451545.0 + 1.0, false);
		const probe = chunk.probes[0];
		const sub = probe.subChunks[0];
		expect(sub.method).toBe(PROBE_METHOD_KEPLER_PURE);
		// At the sub-chunk start ET (jd = 2451545.0 = J2000), M=0 so we're at (a,0,0).
		const pos = probePositionKm(probe, 2451545.0, 3.986e5);
		expect(pos).not.toBeNull();
		expect(pos![0]).toBeCloseTo(aKm, 0);
		expect(pos![1]).toBeCloseTo(0, 5);
		expect(pos![2]).toBeCloseTo(0, 5);
	});

	it('parses a chebyshev sub-chunk and clenshaw-evaluates at tau=-1', () => {
		// One segment, 12 coeffs/axis, position c0 only (constant) at (100, -50, 7).
		const N = 12;
		const cx = new Array(N).fill(0);
		cx[0] = 100;
		const cy = new Array(N).fill(0);
		cy[0] = -50;
		const cz = new Array(N).fill(0);
		cz[0] = 7;
		const payload = [...cx, ...cy, ...cz];
		const buf = buildBuffer(
			2451545.0,
			2451545.0 + 1.0,
			1.0,
			[
				{
					probeId: 42,
					objectType: 13,
					hasLocalized: false,
					firstSubchunkOffset: 0,
					subChunks: [{ method: PROBE_METHOD_CHEBYSHEV, payload }]
				}
			],
			false
		);
		const chunk = parseProbesPayload(buf, 2451545.0, 2451545.0 + 1.0, false);
		const probe = chunk.probes[0];
		const pos = probePositionKm(probe, 2451545.0, 0);
		expect(pos).not.toBeNull();
		expect(pos![0]).toBeCloseTo(100, 5);
		expect(pos![1]).toBeCloseTo(-50, 5);
		expect(pos![2]).toBeCloseTo(7, 5);
	});

	it('decodes float64 coefficients when the zone flag is set', () => {
		// Past float32's mantissa — must round-trip exactly to prove f64 read.
		const N = 12;
		const cx = [1.000000000000001, 2.000000000000002, ...new Array(N - 2).fill(0)];
		const cy = new Array(N).fill(0);
		const cz = new Array(N).fill(0);
		const payload = [...cx, ...cy, ...cz];
		const buf = buildBuffer(
			0,
			1,
			1,
			[
				{
					probeId: 5,
					objectType: 13,
					hasLocalized: false,
					firstSubchunkOffset: 0,
					subChunks: [{ method: PROBE_METHOD_CHEBYSHEV, payload }]
				}
			],
			true
		);
		const chunk = parseProbesPayload(buf, 0, 1, true);
		const sub = chunk.probes[0].subChunks[0];
		expect(sub.method).toBe(PROBE_METHOD_CHEBYSHEV);
		if (sub.method === PROBE_METHOD_CHEBYSHEV) {
			expect(sub.coeffs).toBeInstanceOf(Float64Array);
			expect(sub.coeffs[0]).toBe(cx[0]);
			expect(sub.coeffs[1]).toBe(cx[1]);
		}
	});

	it('handles kepler_drift sub-chunks', () => {
		// 10 floats: a, e, i, om, w, m0, om_dot, w_dot, n, t_anchor_offset.
		const aKm = 10000;
		const buf = buildBuffer(
			2451545.0,
			2451545.0 + 1.0,
			1.0,
			[
				{
					probeId: 7,
					objectType: 13,
					hasLocalized: false,
					firstSubchunkOffset: 0,
					subChunks: [
						{
							method: PROBE_METHOD_KEPLER_DRIFT,
							payload: [aKm, 0, 0, 0, 0, 0, 0, 0, 0, 0]
						}
					]
				}
			],
			false
		);
		const probe = parseProbesPayload(buf, 2451545.0, 2451545.0 + 1.0, false).probes[0];
		const sub = probe.subChunks[0];
		expect(sub.method).toBe(PROBE_METHOD_KEPLER_DRIFT);
		const pos = probePositionKm(probe, 2451545.0, 0);
		expect(pos).not.toBeNull();
		expect(pos![0]).toBeCloseTo(aKm, 0);
	});

	it('returns null outside the probe sub-chunk window', () => {
		const buf = buildBuffer(
			2451545.0,
			2451545.0 + 7.0,
			7.0,
			[
				{
					probeId: 1,
					objectType: 13,
					hasLocalized: false,
					firstSubchunkOffset: 0,
					subChunks: [{ method: PROBE_METHOD_UNCOVERABLE, payload: [] }]
				}
			],
			false
		);
		const probe = parseProbesPayload(buf, 2451545.0, 2451545.0 + 7.0, false).probes[0];
		expect(probePositionKm(probe, 2451550.0, 0)).toBeNull(); // uncoverable
		expect(probePositionKm(probe, 2451530.0, 0)).toBeNull(); // before window
		expect(probePositionKm(probe, 2451600.0, 0)).toBeNull(); // after window
	});

	it('honours first_subchunk_offset for probes that start mid-chunk', () => {
		// Chunk = 14 days, subchunk = 7 days. Probe's first sub-chunk starts at
		// offset 1 → sub starts at chunkStart + 7 days.
		const startJd = 2451545.0;
		const buf = buildBuffer(
			startJd,
			startJd + 14.0,
			7.0,
			[
				{
					probeId: 1,
					objectType: 13,
					hasLocalized: false,
					firstSubchunkOffset: 1,
					subChunks: [
						{
							method: PROBE_METHOD_KEPLER_PURE,
							payload: [10000, 0, 0, 0, 0, 0, 0]
						}
					]
				}
			],
			false
		);
		const probe = parseProbesPayload(buf, startJd, startJd + 14.0, false).probes[0];
		// Before offset window — null.
		expect(probePositionKm(probe, startJd + 3, 3.986e5)).toBeNull();
		// Within offset window — finite.
		expect(probePositionKm(probe, startJd + 10, 3.986e5)).not.toBeNull();
	});
});
