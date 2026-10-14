import { describe, it, expect } from 'vitest';
import type { BodyData, PositionedBody } from '$lib/types/objects';
import { tdbToUtc, utcToTdb } from '$lib/time/jd';
import { allocColumns, packBodiesSliced, writePositions, KIND_KEPLER } from './soa';

const J2000_JD = 2451545.0;

/** Three identical circular orbits differing only in discovery date. */
function threeRows(visibleFromDays: [number, number, number]) {
	const cols = allocColumns(3);
	for (let i = 0; i < 3; i++) {
		cols.kind[i] = KIND_KEPLER;
		cols.a[i] = 1;
		cols.e[i] = 0;
		cols.i[i] = 0;
		cols.om[i] = 0;
		cols.w[i] = 0;
		cols.ma[i] = 0;
		cols.n[i] = 0.5;
		cols.epoch[i] = J2000_JD;
		cols.visibleFromDays[i] = visibleFromDays[i];
	}
	return cols;
}

/** Solve at `jd` and return how many points were written (the draw count). */
function countAt(cols: ReturnType<typeof threeRows>, jd: number): number {
	const out = new Float32Array(3 * 3);
	return writePositions(cols, jd, 0, 0, 0, 0, 0, 0, out);
}

describe('writePositions — discovery gating', () => {
	// row0: never gated (NaN); row1: discovered ~2020; row2: discovered ~1990.
	const cols = threeRows([NaN, 7305, -3653]);

	it('hides bodies not yet discovered at the tick jd', () => {
		// jd = J2000 (jdDays 0): NaN visible, +7305 hidden, -3653 visible.
		expect(countAt(cols, J2000_JD)).toBe(2);
	});

	it('shows every body once jd passes all discovery dates', () => {
		expect(countAt(cols, J2000_JD + 10000)).toBe(3);
	});

	it('hides every dated body before its discovery, keeping NaN visible', () => {
		expect(countAt(cols, J2000_JD - 5000)).toBe(1);
	});
});

describe('writePositions — validity window', () => {
	/** A moon chunk's window, in TDB, and a row in it. */
	const START = 2461300.5;
	const END = 2461400.5;
	const row = (equatorial: boolean): PositionedBody =>
		({
			data: {
				id: 'naif-65000',
				a: 0.01,
				e: 0,
				i: 0,
				om: 0,
				w: 0,
				ma: 0,
				n: 1,
				epoch: START,
				equatorial,
				validityStart: START,
				validityEnd: END
			} as BodyData
		}) as PositionedBody;

	it('shows a TDB chunk from the moment the clock reaches its start', async () => {
		// The zone swaps in the chunk once the clock's TDB passes START, 69 s before the clock does.
		const cols = await packBodiesSliced([row(false)]);
		const swap = tdbToUtc(START) + 1 / 86400;
		expect(utcToTdb(swap)).toBeGreaterThan(START);
		expect(writePositions(cols, swap, 0, 0, 0, 0, 0, 0, new Float32Array(3))).toBe(1);
		expect(
			writePositions(cols, tdbToUtc(END) + 1 / 86400, 0, 0, 0, 0, 0, 0, new Float32Array(3))
		).toBe(0);
	});

	it('keeps the window of a TLE row in UTC', async () => {
		const cols = await packBodiesSliced([row(true)]);
		expect(cols.validityStart).toBe(START);
		expect(cols.validityEnd).toBe(END);
	});
});
