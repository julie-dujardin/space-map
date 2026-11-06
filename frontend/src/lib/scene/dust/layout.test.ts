import { describe, expect, it } from 'vitest';
import { DUST_BOX, distanceToBox, rayThroughBox } from './layout';

describe('distance to the box', () => {
	it('is 0 inside and on the faces', () => {
		expect(distanceToBox([0, 0, 0])).toBe(0);
		expect(distanceToBox([DUST_BOX[0], 0, -DUST_BOX[2]])).toBe(0);
	});

	it('is the gap to a face, and to a corner', () => {
		expect(distanceToBox([0, 0, DUST_BOX[2] + 500])).toBe(500);
		expect(distanceToBox([DUST_BOX[0] + 300, DUST_BOX[1] + 400, 0])).toBe(500);
	});
});

describe('ray through the box', () => {
	it('starts at 0 from inside', () => {
		const { near, far } = rayThroughBox([0, 0, 0], [0, 0, 1]);
		expect(near).toBe(0);
		expect(far).toBeCloseTo(DUST_BOX[2], 3);
	});

	it('leaves by the nearest face', () => {
		const { far } = rayThroughBox([0, 0, 0], [Math.SQRT1_2, 0, Math.SQRT1_2]);
		expect(far).toBeCloseTo(DUST_BOX[2] * Math.SQRT2, 2);
	});

	it('enters the top of the box from above', () => {
		const { near, far } = rayThroughBox([0, 0, 8_000], [0, 0, -1]);
		expect(near).toBeCloseTo(8_000 - DUST_BOX[2], 2);
		expect(far).toBeCloseTo(8_000 + DUST_BOX[2], 2);
	});

	it('reports a miss', () => {
		const { near, far } = rayThroughBox([0, 0, 8_000], [0, 0, 1]);
		expect(far).toBeLessThanOrEqual(near);
	});
});
