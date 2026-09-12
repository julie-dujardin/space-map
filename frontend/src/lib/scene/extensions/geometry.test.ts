import { describe, expect, it } from 'vitest';
import {
	circlePoints,
	meanDirection,
	newellNormal,
	planeBasis,
	slerpDirection,
	triangulate
} from './geometry';
import type { OffsetKm } from './anchor';

const dot = (a: OffsetKm, b: OffsetKm) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const length = (v: OffsetKm) => Math.hypot(v[0], v[1], v[2]);

describe('planeBasis', () => {
	it('answers two unit vectors at right angles to the normal and to each other', () => {
		for (const normal of [
			[0, 0, 1],
			[1, 0, 0],
			[1, 2, 3],
			[0, -1, 0]
		] as OffsetKm[]) {
			const [a, b] = planeBasis(normal);
			expect(length(a)).toBeCloseTo(1, 12);
			expect(length(b)).toBeCloseTo(1, 12);
			expect(dot(a, b)).toBeCloseTo(0, 12);
			expect(dot(a, normal)).toBeCloseTo(0, 12);
			expect(dot(b, normal)).toBeCloseTo(0, 12);
		}
	});

	it('stands in a basis for a normal of no length', () => {
		const [a, b] = planeBasis([0, 0, 0]);
		expect(dot(a, b)).toBeCloseTo(0, 12);
	});
});

describe('circlePoints', () => {
	it('puts every point at the radius asked for', () => {
		for (const point of circlePoints(700, { steps: 32 })) {
			expect(length(point)).toBeCloseTo(700, 9);
		}
	});

	it('lies in the plane at right angles to the normal', () => {
		const normal: OffsetKm = [1, 1, 0];
		for (const point of circlePoints(500, { normal, steps: 16 })) {
			expect(dot(point, normal)).toBeCloseTo(0, 9);
		}
	});

	it('draws in the ecliptic plane when no normal is given', () => {
		for (const point of circlePoints(100, { steps: 8 })) expect(point[2]).toBeCloseTo(0, 12);
	});

	it('never draws fewer points than a triangle', () => {
		expect(circlePoints(1, { steps: 1 })).toHaveLength(3);
	});
});

describe('triangulate', () => {
	it('cuts a square into two triangles', () => {
		const square: OffsetKm[] = [
			[0, 0, 0],
			[10, 0, 0],
			[10, 10, 0],
			[0, 10, 0]
		];
		expect(triangulate(square)).toHaveLength(6);
	});

	it('cuts a ring however it is turned', () => {
		// The same ring standing on edge: a fill worked out in the ecliptic plane
		// alone would collapse to a line and cut nothing.
		const ring = circlePoints(300, { normal: [1, 0, 0], steps: 24 });
		expect(triangulate(ring)).toHaveLength(3 * 22);
	});

	it('draws nothing from fewer than three points', () => {
		expect(
			triangulate([
				[0, 0, 0],
				[1, 0, 0]
			])
		).toEqual([]);
	});
});

describe('newellNormal', () => {
	it('is at right angles to the plane the points lie in', () => {
		const ring = circlePoints(50, { normal: [0, 1, 1], steps: 12 });
		const normal = newellNormal(ring);
		expect(dot(normal, [0, 1, 1]) / (length(normal) * Math.SQRT2)).toBeCloseTo(1, 9);
	});

	it('falls back to the ecliptic pole for points on one line', () => {
		expect(
			newellNormal([
				[0, 0, 0],
				[1, 0, 0],
				[2, 0, 0]
			])
		).toEqual([0, 0, 1]);
	});
});

describe('slerpDirection', () => {
	it('stays on the sphere between two directions', () => {
		const half = slerpDirection([1, 0, 0], [0, 1, 0], 0.5);
		expect(length(half)).toBeCloseTo(1, 12);
		expect(half[0]).toBeCloseTo(Math.SQRT1_2, 12);
		expect(half[1]).toBeCloseTo(Math.SQRT1_2, 12);
	});

	it('reaches both ends', () => {
		expect(slerpDirection([1, 0, 0], [0, 0, 1], 0)).toEqual([1, 0, 0]);
		const end = slerpDirection([1, 0, 0], [0, 0, 1], 1);
		expect(end[2]).toBeCloseTo(1, 12);
	});

	it('holds still between a direction and itself', () => {
		expect(slerpDirection([0, 0, 1], [0, 0, 1], 0.3)).toEqual([0, 0, 1]);
	});
});

describe('meanDirection', () => {
	it('is the middle of the directions given', () => {
		const dirs = new Float64Array([1, 0, 0, 0, 1, 0]);
		const middle = meanDirection(dirs, 2);
		expect(middle[0]).toBeCloseTo(Math.SQRT1_2, 12);
		expect(length(middle)).toBeCloseTo(1, 12);
	});

	it('takes the first direction when they cancel out', () => {
		const dirs = new Float64Array([1, 0, 0, -1, 0, 0]);
		expect(meanDirection(dirs, 2)).toEqual([1, 0, 0]);
	});
});
