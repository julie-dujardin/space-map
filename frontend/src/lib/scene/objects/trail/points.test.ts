import { describe, expect, it } from 'vitest';
import { NUM_TRAIL_POINTS, writeTrailAlphas } from './points';

/** Vertices along the x axis, at these distances from the body. */
function line(distances: number[]): Float32Array {
	const pos = new Float32Array(distances.length * 3);
	distances.forEach((d, k) => (pos[k * 3] = d));
	return pos;
}

function alphas(distances: number[], isOpenCurve: boolean, useTrail: boolean) {
	const full = new Float32Array(distances.length);
	const trail = new Float32Array(distances.length);
	writeTrailAlphas(full, trail, line(distances), isOpenCurve, useTrail);
	return { full, trail };
}

const even = (n: number) => Array.from({ length: n }, (_, k) => k);

describe('writeTrailAlphas', () => {
	it.each([2, 4, 26, 160, NUM_TRAIL_POINTS + 1])('an open trail of %i vertices ends at 0', (n) => {
		const { full, trail } = alphas(even(n), true, true);
		expect(full[n - 1]).toBe(0);
		expect(trail[n - 1]).toBe(0);
	});

	it('an open trail fades over its nearest third, like an SGP4 window', () => {
		const { trail } = alphas(even(NUM_TRAIL_POINTS), true, true);
		expect(trail[0]).toBeCloseTo(0.35);
		expect(trail[Math.ceil(NUM_TRAIL_POINTS / 3)]).toBe(0);
		expect(trail[Math.floor(NUM_TRAIL_POINTS / 6)]).toBeCloseTo(0.35 / 2, 2);
	});

	it('an open trail fades by length, however its vertices are spaced', () => {
		// Dense at the body and sparse behind it, like a probe past periapsis.
		const dense = Array.from({ length: 100 }, (_, k) => k * 0.01);
		const { trail } = alphas([...dense, 5, 10, 30], true, true);
		expect(trail[99]).toBeGreaterThan(0.3);
		expect(trail[100]).toBeCloseTo(0.35 / 2, 5);
		expect(trail[101]).toBe(0);
	});

	it('a closed trail keeps its floor and its vertex ramp', () => {
		// The warp of an ellipse moves vertices to periapsis: length must not count.
		const warped = even(NUM_TRAIL_POINTS + 1).map((k) => k ** 2);
		const { full, trail } = alphas(warped, false, true);
		expect(full[NUM_TRAIL_POINTS]).toBeCloseTo(0.55 / 3);
		expect(trail[Math.floor(NUM_TRAIL_POINTS / 6)]).toBeCloseTo(0.35 / 2, 2);
	});

	it('a body with no partial trail copies the full ramp', () => {
		const { full, trail } = alphas(even(NUM_TRAIL_POINTS + 1), false, false);
		expect(trail).toEqual(full);
	});

	it('a trail with no length keeps the head alpha', () => {
		const { full, trail } = alphas([0, 0, 0], true, true);
		expect(full[2]).toBeCloseTo(0.55);
		expect(trail[2]).toBeCloseTo(0.35);
	});
});
