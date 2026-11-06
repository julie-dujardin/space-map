import { describe, expect, it } from 'vitest';
import type { Vec3 } from '$lib/scene/dust/octahedral';
import { GALAXY_FROM_PC, GALAXY_FULL_PC, GALAXY_RADIUS_PC, galaxyFrame } from './outside';

const CENTRE: Vec3 = [8277, 0, -21];
const dot = (a: ArrayLike<number>, b: ArrayLike<number>) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const columns = (axes: Float32Array) => [axes.slice(0, 3), axes.slice(3, 6), axes.slice(6, 9)];
const at = (u: Vec3, d: number): Vec3 => {
	const n = Math.hypot(...u);
	return [CENTRE[0] + (u[0] / n) * d, CENTRE[1] + (u[1] / n) * d, CENTRE[2] + (u[2] / n) * d];
};

describe('the map about the Galaxy', () => {
	it('is not made from within the disc', () => {
		expect(galaxyFrame([0, 0, 0], CENTRE)).toBeNull();
		expect(galaxyFrame([0, 0, 8000], CENTRE)).toBeNull();
		expect(galaxyFrame(at([0, -1, 0], GALAXY_FROM_PC - 1), CENTRE)).toBeNull();
	});

	it('takes over with no step across its range of distance', () => {
		let last = 0;
		for (let d = GALAXY_FROM_PC + 100; d <= GALAXY_FULL_PC + 2000; d += 100) {
			const share = galaxyFrame(at([-0.5, -0.3, 0.6], d), CENTRE)!.share;
			expect(share).toBeGreaterThanOrEqual(last);
			expect(share - last).toBeLessThan(0.03);
			last = share;
		}
		expect(last).toBe(1);
	});

	it('looks at the centre from its origin, with orthonormal axes and north up', () => {
		const origin = at([-0.5, -0.3, 0.6], 30_000);
		const frame = galaxyFrame(origin, CENTRE)!;
		const [right, up, forward] = columns(frame.axes);
		for (const [a, b, want] of [
			[right, right, 1],
			[up, up, 1],
			[forward, forward, 1],
			[right, up, 0],
			[up, forward, 0],
			[forward, right, 0]
		] as const) {
			expect(dot(a, b)).toBeCloseTo(want, 6);
		}
		const to = CENTRE.map((c, i) => (c - origin[i]) / 30_000);
		expect(dot(forward, to)).toBeCloseTo(1, 6);
		expect(up[2]).toBeGreaterThan(0);
	});

	it('holds the sphere of the Galaxy, its half width set by the distance', () => {
		const frame = galaxyFrame(at([0, -1, 0], 30_000), CENTRE)!;
		const sin = GALAXY_RADIUS_PC / 30_000;
		expect(frame.tan).toBeCloseTo(sin / Math.sqrt(1 - sin * sin), 9);
		// Never wider than 60 degrees, so a texel at the edge is at most four at the centre.
		expect(galaxyFrame(at([0, -1, 0], GALAXY_FROM_PC + 10), CENTRE)!.tan).toBeCloseTo(
			Math.sqrt(3),
			6
		);
	});

	it('has a frame looking along the pole, with the side away from the Sun up', () => {
		const frame = galaxyFrame(at([0, 0, 1], 30_000), CENTRE)!;
		const [right, up] = columns(frame.axes);
		expect(Number.isFinite(right[0] + up[0])).toBe(true);
		expect(up[0]).toBeCloseTo(-1, 6);
	});
});
