import { describe, expect, it } from 'vitest';
import { COARSE_SEGS, buildGridArrays, nestedStepLevel, planNestedGrid } from './terrain-grid';

const MAX_LEVEL = 6;
const PIXEL = (2 * Math.PI) / (2048 * 2 ** MAX_LEVEL);
const BAND = 24;
/** Mars: the relief stands about 15 km over a radius of 3,390 km. */
const PEAK = 15 / 3390;

function plan(theta: number, phi: number, altitude: number) {
	const stepLevel = nestedStepLevel(altitude, MAX_LEVEL, BAND);
	return planNestedGrid(theta, phi, altitude, PEAK, MAX_LEVEL, BAND, stepLevel);
}

function steps(at: Float64Array): number[] {
	return Array.from(at.slice(1), (angle, i) => angle - at[i]);
}

describe('nestedStepLevel', () => {
	it('is one pixel of the finest level on the ground', () => {
		expect(nestedStepLevel(1e-6, MAX_LEVEL, BAND)).toBe(0);
	});

	it('rises by one each time the camera is twice as high', () => {
		const at = (altitude: number) => nestedStepLevel(altitude, MAX_LEVEL, BAND);
		expect(at(0.02) - at(0.01)).toBe(1);
		expect(at(0.04) - at(0.02)).toBe(1);
	});

	it('keeps the level in place near the line between two', () => {
		const altitude = BAND * PIXEL * 2 ** 3.1;
		expect(nestedStepLevel(altitude, MAX_LEVEL, BAND)).toBe(4);
		expect(nestedStepLevel(altitude, MAX_LEVEL, BAND, 3)).toBe(3);
	});
});

describe('planNestedGrid', () => {
	it('covers the whole body, from pole to pole and seam to seam', () => {
		const { rows, columns } = plan(1.2, 2, 1e-6);
		expect([rows.at[0], rows.at.at(-1)]).toEqual([0, Math.PI]);
		expect([columns.at[0], columns.at.at(-1)]).toEqual([0, 2 * Math.PI]);
		expect(steps(rows.at).every((step) => step > 0)).toBe(true);
		expect(steps(columns.at).every((step) => step > 0)).toBe(true);
	});

	it('has cells of one pixel under a camera on the ground', () => {
		const { rows, innerRadius } = plan(1.2, 2, 1e-6);
		expect(Math.min(...steps(rows.at))).toBeCloseTo(PIXEL, 12);
		expect(innerRadius).toBeCloseTo(BAND * PIXEL, 12);
	});

	it('has cells that never shrink away from the camera, out to the coarse grid', () => {
		const { rows } = plan(1.2, 2, 1e-6);
		const south = steps(rows.at).filter((_, i) => rows.at[i] >= 1.2);
		for (let i = 1; i < south.length; i++) {
			expect(south[i]).toBeGreaterThan(south[i - 1] * 0.999);
		}
		expect(south.at(-1)).toBeCloseTo(Math.PI / COARSE_SEGS, 12);
	});

	it('doubles its cells from one band to the next', () => {
		const { rows } = plan(1.2, 2, 1e-6);
		const widths = new Set(steps(rows.at).map((step) => Math.round(step / PIXEL)));
		for (const cells of [1, 2, 4, 8, 16, 32, 64]) expect(widths.has(cells)).toBe(true);
	});

	it('names for each row the level whose pixels are as wide as its cells', () => {
		const { rows } = plan(1.2, 2, 1e-6);
		const centre = rows.at.findIndex((angle) => angle >= 1.2);
		expect(rows.level[centre]).toBe(MAX_LEVEL);
		expect(rows.level[0]).toBe(0);
		expect(Math.max(...rows.level)).toBe(MAX_LEVEL);
	});

	it('keeps its vertices in place when it is built around another point', () => {
		const a = plan(1.2, 2, 1e-6);
		const b = plan(1.2 + 7.3 * PIXEL, 2, 1e-6);
		const held = new Set(Array.from(a.rows.at, (angle) => Math.round(angle / PIXEL)));
		const near = Array.from(b.rows.at).filter((angle) => Math.abs(angle - 1.2) < 10 * PIXEL);
		expect(near.length).toBeGreaterThan(10);
		for (const angle of near) {
			expect(angle / PIXEL).toBeCloseTo(Math.round(angle / PIXEL), 6);
			expect(held.has(Math.round(angle / PIXEL))).toBe(true);
		}
	});

	it('reaches past the horizon, to the ground that stands above it', () => {
		const { rows } = plan(1.2, 2, 1e-6);
		const gaps = steps(rows.at);
		const banded = Array.from(rows.at).filter((_, i) => gaps[i] < (0.9 * Math.PI) / COARSE_SEGS);
		expect(banded.at(-1)! - 1.2).toBeGreaterThan(Math.acos(1 / (1 + PEAK)));
	});

	it('goes all the way round near a pole, with no more columns than rows', () => {
		const { rows, columns } = plan(0.001, 2, 1e-6);
		expect(columns.at.length).toBeLessThanOrEqual(rows.at.length * 1.5);
	});

	it('stays a modest grid at every height and latitude', () => {
		for (const altitude of [1e-6, 1e-3, 0.03, 0.3]) {
			for (const theta of [0.0001, 0.5, 1.5708, 3.1]) {
				const { rows, columns } = plan(theta, 6.2, altitude);
				expect(rows.at.length * columns.at.length).toBeLessThan(300_000);
			}
		}
	});
});

describe('buildGridArrays', () => {
	const thetas = Float64Array.of(0, Math.PI / 2, Math.PI);
	const phis = Float64Array.of(0, Math.PI, 2 * Math.PI);

	it('puts each vertex on the sphere, as SphereGeometry does', () => {
		const { positions, uvs } = buildGridArrays(2, thetas, phis);
		// Row 1, column 0: the equator at φ = 0 is −X.
		expect(Array.from(positions.slice(9, 12))).toEqual([-2, expect.closeTo(0, 6), 0]);
		expect(Array.from(uvs.slice(6, 8))).toEqual([0, 0.5]);
	});

	it('lifts each vertex by its own height', () => {
		const rise = new Float32Array(9).fill(10);
		const { positions } = buildGridArrays(2, thetas, phis, rise, 0.01);
		expect(Math.hypot(positions[9], positions[10], positions[11])).toBeCloseTo(2.1, 6);
	});

	it('leaves out the triangles that close to a point at a pole', () => {
		const { indices } = buildGridArrays(1, thetas, phis);
		expect(indices.length).toBe(4 * 3);
	});
});
