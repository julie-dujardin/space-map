import { describe, it, expect } from 'vitest';
import { triangleNormalKm, trianglePointKm } from './rendered-surface';

/** Flat quad in the z=0 plane at radius ~1000 on +y, corners TL/TR/BL/BR. */
const flat: [number, number, number][] = [
	[-1, 1000, -1],
	[1, 1000, -1],
	[-1, 1000, 1],
	[1, 1000, 1]
];

/** Same quad with BL lifted — the two facets now have distinct normals. */
const bent: [number, number, number][] = [
	[-1, 1000, -1],
	[1, 1000, -1],
	[-1, 1002, 1],
	[1, 1000, 1]
];

describe('triangleNormalKm', () => {
	it('points outward (away from the body centre) on a flat facet', () => {
		const n = triangleNormalKm(flat, 0.5, 0.5);
		expect(n[0]).toBeCloseTo(0, 12);
		expect(n[1]).toBeCloseTo(1, 12);
		expect(n[2]).toBeCloseTo(0, 12);
	});

	it('matches the facet trianglePointKm seats on across the diagonal', () => {
		// tx > ty → TL-TR-BR triangle, untouched by the BL lift.
		const nUpper = triangleNormalKm(bent, 0.8, 0.2);
		expect(nUpper[1]).toBeCloseTo(1, 12);
		// tx < ty → TL-BL-BR triangle, tilted by the lifted BL corner.
		const nLower = triangleNormalKm(bent, 0.2, 0.8);
		expect(nLower[1]).toBeLessThan(1);
		expect(Math.hypot(...nLower)).toBeCloseTo(1, 12);
		// The seat and the normal must agree on the facet: a point of the lower
		// triangle lies on the plane through TL with normal nLower.
		const seat = trianglePointKm(bent, 0.2, 0.8);
		const d =
			(seat[0] - bent[0][0]) * nLower[0] +
			(seat[1] - bent[0][1]) * nLower[1] +
			(seat[2] - bent[0][2]) * nLower[2];
		expect(d).toBeCloseTo(0, 10);
	});
});
