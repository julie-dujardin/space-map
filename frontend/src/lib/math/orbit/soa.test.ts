import { describe, it, expect } from 'vitest';
import { allocColumns, writePositions, KIND_KEPLER } from './soa';

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
