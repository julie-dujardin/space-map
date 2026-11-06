import { describe, expect, it } from 'vitest';
import { K_G, dustBounds } from './extinction';
import type { NestLevel } from './nest';
import { nodeShift, sampleNode } from './node-shift';
import type { Vec3 } from './octahedral';

const FLOOR = 1e-6;
const SPAN = Math.log1p(0.1 / FLOOR);

/** A box of empty space with one wall of dust: x from `from` to `to`. */
function wall(from: number, to: number, density: number): NestLevel {
	const size: Vec3 = [64, 8, 8];
	const half: Vec3 = [2_000, 2_000, 2_000];
	const codes = new Uint8Array(size[0] * size[1] * size[2]);
	const code = Math.round((Math.log1p(density / FLOOR) / SPAN) * 255);
	for (let z = 0; z < 8; z++) {
		for (let y = 0; y < 8; y++) {
			for (let x = 0; x < 64; x++) {
				const at = ((x + 0.5) / 64) * 4_000 - 2_000;
				if (at >= from && at <= to) codes[x + 64 * (y + 8 * z)] = code;
			}
		}
	}
	return { half, floor: FLOOR, span: SPAN, size, codes };
}

const toNest = (v: readonly [number, number, number]): Vec3 => [v[0], v[1], v[2]];

/** The bound byte of stars that may gain without limit. */
const free = (count: number): Uint8Array => new Uint8Array(count).fill(255);

/** Rows on the x axis at the given distances, from a node centre at 0. */
const rowsAt = (...x: number[]): Float32Array =>
	new Float32Array(x.flatMap((value) => [value, 0, 0]));

describe('node shift', () => {
	const levels = [wall(400, 600, 1e-2)];

	it('is exactly zero from the Sun', () => {
		const sample = sampleNode(levels, rowsAt(100, 800, 1_500), free(3), [0, 0, 0], toNest);
		expect(Math.abs(nodeShift(levels, sample, [0, 0, 0]))).toBe(0);
	});

	it('dims stars that the camera sees behind a wall the Sun does not', () => {
		const sample = sampleNode(levels, rowsAt(300), free(1), [0, 0, 0], toNest);
		expect(sample.sun[0]).toBeLessThan(1e-3);
		const shift = nodeShift(levels, sample, [800, 0, 0]);
		expect(shift).toBeGreaterThan(1);
	});

	it('brightens stars past a wall from a camera behind it', () => {
		const sample = sampleNode(levels, rowsAt(800), free(1), [0, 0, 0], toNest);
		expect(sample.sun[0]).toBeGreaterThan(1);
		const shift = nodeShift(levels, sample, [1_000, 0, 0]);
		expect(shift).toBeLessThan(-1);
	});

	it('takes the mean in flux, so a clear half of the node holds the light', () => {
		const sample = sampleNode(levels, rowsAt(300, 800), free(2), [0, 0, 0], toNest);
		expect(sample.places.length).toBe(2);
		const each = [0, 1].map((i) => {
			const one = {
				places: [sample.places[i]],
				sun: sample.sun.slice(i, i + 1),
				bound: sample.bound.slice(i, i + 1)
			};
			return nodeShift(levels, one, [1_000, 0, 0]);
		});
		const both = nodeShift(levels, sample, [1_000, 0, 0]);
		const mag = (dust: number) => Math.pow(10, -0.4 * K_G * dust);
		expect(mag(both)).toBeCloseTo((mag(each[0]) + mag(each[1])) / 2, 5);
	});

	it('lets a star gain no more than its bound', () => {
		// BP-RP 0.5 and G -2 allow 1.8 mag of A0.
		const bound = dustBounds([0.5], [-2], new Uint8Array(1));
		const sample = sampleNode(levels, rowsAt(800), bound, [0, 0, 0], toNest);
		const shift = nodeShift(levels, sample, [1_000, 0, 0]);
		expect(shift).toBeCloseTo(-sample.bound[0], 6);
		expect(shift).toBeGreaterThan(-2);
	});

	it('has no shift for a node with no rows', () => {
		const sample = sampleNode(levels, rowsAt(), free(0), [0, 0, 0], toNest);
		expect(nodeShift(levels, sample, [1_000, 0, 0])).toBe(0);
	});

	it('spreads its samples over the rows', () => {
		const rows = Array.from({ length: 100 }, (_, i) => i);
		const sample = sampleNode(levels, rowsAt(...rows), free(100), [5, 0, 0], toNest);
		expect(sample.places.length).toBe(8);
		expect(sample.places[0][0]).toBeCloseTo(11, 6);
		expect(sample.places[7][0]).toBeCloseTo(98, 6);
	});
});
