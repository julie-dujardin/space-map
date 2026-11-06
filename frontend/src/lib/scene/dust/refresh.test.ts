import { describe, expect, it } from 'vitest';
import type { NestLevel } from './nest';
import type { Vec3 } from './octahedral';
import { REFRESH_SHARE, RefreshPacer, nearestStructure, refreshReach } from './refresh';
import { passJitter } from './star-dust';

const FLOOR = 1e-6;
const SPAN = Math.log1p(0.1 / FLOOR);

/** Empty space with a shell of dust from `inner` to `outer` pc. */
function shell(inner: number, outer: number, density: number): NestLevel {
	const n = 64;
	const size: Vec3 = [n, n, n];
	const half: Vec3 = [1_000, 1_000, 1_000];
	const codes = new Uint8Array(n * n * n);
	const code = Math.round((Math.log1p(density / FLOOR) / SPAN) * 255);
	for (let z = 0; z < n; z++) {
		for (let y = 0; y < n; y++) {
			for (let x = 0; x < n; x++) {
				const p = [x, y, z].map((i) => ((i + 0.5) / n) * 2_000 - 1_000);
				const r = Math.hypot(p[0], p[1], p[2]);
				if (r >= inner && r <= outer) codes[x + n * (y + n * z)] = code;
			}
		}
	}
	return { half, floor: FLOOR, span: SPAN, size, codes };
}

describe('nearest structure', () => {
	it('finds a wall of dust', () => {
		const found = nearestStructure([shell(200, 300, 5e-2)], [0, 0, 0]);
		expect(found).toBeGreaterThan(150);
		expect(found).toBeLessThan(350);
	});

	it('is nearer from a place near the wall', () => {
		const levels = [shell(200, 300, 5e-2)];
		expect(nearestStructure(levels, [150, 0, 0])).toBeLessThan(
			nearestStructure(levels, [0, 0, 0]) * 0.6
		);
	});

	it('stays above its floor inside dense dust', () => {
		expect(nearestStructure([shell(0, 1_000, 9e-2)], [0, 0, 0])).toBe(5);
	});

	it('puts a camera outside the box at least as far as the box', () => {
		// 100 kpc over the top face: no dust is nearer, and the search stops at 40 kpc.
		const found = nearestStructure([shell(200, 300, 5e-2)], [0, 0, 103_000]);
		expect(found).toBe(100_000);
		expect(refreshReach(found)).toBeGreaterThan(refreshReach(40_000));
	});

	it('leaves a camera inside the box to the search', () => {
		expect(nearestStructure([shell(200, 300, 5e-2)], [0, 0, 0])).toBeLessThan(350);
	});

	it('gives a reach in proportion', () => {
		expect(refreshReach(100)).toBeCloseTo(100 * REFRESH_SHARE, 12);
	});
});

describe('refresh pacer', () => {
	it('leaves a fast device free', () => {
		const pacer = new RefreshPacer();
		for (let i = 0; i < 50; i++) pacer.note(10);
		expect(pacer.intervalMs).toBe(0);
		expect(pacer.due(0)).toBe(true);
	});

	it('spaces refreshes out when frames are slow', () => {
		const pacer = new RefreshPacer();
		for (let i = 0; i < 4; i++) pacer.note(60);
		expect(pacer.intervalMs).toBeGreaterThanOrEqual(100);
		pacer.refreshed(1_000);
		expect(pacer.due(1_000 + pacer.intervalMs - 1)).toBe(false);
		expect(pacer.due(1_000 + pacer.intervalMs)).toBe(true);
	});

	it('has a longest wait', () => {
		const pacer = new RefreshPacer();
		for (let i = 0; i < 100; i++) pacer.note(200);
		expect(pacer.intervalMs).toBeLessThanOrEqual(1_600);
	});

	it('comes back when frames are fast again', () => {
		const pacer = new RefreshPacer();
		for (let i = 0; i < 20; i++) pacer.note(100);
		for (let i = 0; i < 40; i++) pacer.note(8);
		expect(pacer.intervalMs).toBe(0);
	});

	it('takes no frame of no length', () => {
		const pacer = new RefreshPacer();
		pacer.note(0);
		expect(pacer.intervalMs).toBe(0);
	});
});

describe('pass jitter', () => {
	it('cuts the step into even parts', () => {
		for (const passes of [1, 2, 4, 8]) {
			const all = Array.from({ length: passes }, (_, pass) => passJitter(pass, passes));
			const even = Array.from({ length: passes }, (_, k) => (k + 0.5) / passes);
			expect(all.toSorted((a, b) => a - b)).toEqual(even);
		}
	});

	it('samples the middle of the step in a single pass', () => {
		expect(passJitter(0, 1)).toBe(0.5);
	});

	it('covers both halves of the step in the first two passes', () => {
		expect(Math.abs(passJitter(1, 8) - passJitter(0, 8))).toBe(0.5);
	});
});
