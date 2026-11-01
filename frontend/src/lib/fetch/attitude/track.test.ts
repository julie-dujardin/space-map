import { describe, it, expect } from 'vitest';
import { Quaternion } from 'three';
import { AttitudeTrack } from './track';
import type { AttitudeChunk } from './parse';
import type { ProbeAttitude } from '$lib/fetch/objects/object-data';
import { tdbToUtc } from '$lib/time/jd';

const START = 2460000;
const END = START + 100;

function track(holes?: [number, number][]): AttitudeTrack {
	const manifest: ProbeAttitude = {
		frame: 'F',
		start_jd: START,
		end_jd: END,
		n_keyframes: 2,
		baselines: null,
		files: [{ name: '0.bin.gz', start_jd: START, end_jd: END, n_keyframes: 2 }],
		holes
	};
	return new AttitudeTrack('1', manifest);
}

const covers = (t: AttitudeTrack, tdb: number) => t.covers(tdbToUtc(tdb));

/** A track with its one chunk decoded, so a SLERP needs no fetch. */
function resident(holes?: [number, number][]): AttitudeTrack {
	const t = track(holes);
	const chunk: AttitudeChunk = {
		times: Float64Array.of(START, END),
		quats: Float32Array.of(1, 0, 0, 0, 1, 0, 0, 0)
	};
	(t as unknown as { chunks: Map<number, AttitudeChunk> }).chunks.set(0, chunk);
	return t;
}

describe('AttitudeTrack holes', () => {
	it('has no attitude strictly inside a hole', () => {
		const t = track([
			[START + 10, START + 20],
			[START + 50, START + 60]
		]);
		for (const inside of [10.001, 15, 19.999, 51, 59])
			expect(covers(t, START + inside)).toBe(false);
	});

	it('has attitude between holes, up to their edges', () => {
		const t = track([
			[START + 10, START + 20],
			[START + 50, START + 60]
		]);
		for (const outside of [0, 5, 25, 45, 65, 100]) expect(covers(t, START + outside)).toBe(true);
		const justOff = 1e-6;
		for (const edge of [10, 50]) expect(covers(t, START + edge - justOff)).toBe(true);
		for (const edge of [20, 60]) expect(covers(t, START + edge + justOff)).toBe(true);
	});

	it('reads a bundle with no holes as continuous', () => {
		expect(covers(track(undefined), START + 15)).toBe(true);
		expect(covers(track([]), START + 15)).toBe(true);
	});

	it('stops the SLERP that would otherwise run across a hole', () => {
		const out = new Quaternion();
		const inside = tdbToUtc(START + 15);
		expect(resident().orientationAt(inside, out)).toBe(true);
		const holed = resident([[START + 10, START + 20]]);
		expect(holed.orientationAt(inside, out)).toBe(false);
		expect(holed.orientationAt(tdbToUtc(START + 5), out)).toBe(true);
	});

	it('still ends at the coverage edges', () => {
		const t = track([[START + 10, START + 20]]);
		expect(covers(t, START - 1)).toBe(false);
		expect(covers(t, END + 1)).toBe(false);
	});
});
