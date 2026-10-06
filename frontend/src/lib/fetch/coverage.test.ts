import { describe, expect, it } from 'vitest';
import type { GlobalObjectData } from '$lib/fetch/objects/object-data';
import { canBePlaced, nearestCoveredJd, type CoverageWindow } from './coverage';

const MINUTE = 1 / 1440;

/** Mir: its first two windows, with the hole of July 1986 between them. */
const MIR: CoverageWindow[] = [
	[2446480.5, 2446608.0],
	[2446643.0, 2446825.0]
];

describe('nearestCoveredJd', () => {
	it('keeps a date a window holds', () => {
		expect(nearestCoveredJd(MIR, 2446500)).toBe(2446500);
	});

	it('goes just inside the end of the last window from a later date', () => {
		expect(nearestCoveredJd(MIR, 2461319)).toBeCloseTo(2446825.0 - MINUTE, 9);
	});

	it('goes just inside the start of the first window from an earlier date', () => {
		expect(nearestCoveredJd(MIR, 2440000)).toBeCloseTo(2446480.5 + MINUTE, 9);
	});

	it('takes the nearer edge from inside a hole', () => {
		expect(nearestCoveredJd(MIR, 2446610)).toBeCloseTo(2446608.0 - MINUTE, 9);
		expect(nearestCoveredJd(MIR, 2446641)).toBeCloseTo(2446643.0 + MINUTE, 9);
	});

	it('treats an edge itself as outside: it has no sample', () => {
		expect(nearestCoveredJd(MIR, 2446608.0)).toBeCloseTo(2446608.0 - MINUTE, 9);
	});

	it('holds every date inside a window that is open on a side', () => {
		const eros: CoverageWindow[] = [[2412765.5, Infinity]];
		expect(nearestCoveredJd(eros, 2469000)).toBe(2469000);
		expect(nearestCoveredJd(eros, 2400000)).toBeCloseTo(2412765.5 + MINUTE, 9);
		expect(nearestCoveredJd([[-Infinity, Infinity]], 0)).toBe(0);
	});

	it('stays inside a window shorter than two insets', () => {
		const jd = nearestCoveredJd([[100, 100 + MINUTE]], 200);
		expect(jd).toBeGreaterThan(100);
		expect(jd).toBeLessThan(100 + MINUTE);
	});

	it('has no date for an object with no window', () => {
		expect(nearestCoveredJd([], 2461319)).toBeNull();
	});
});

describe('canBePlaced', () => {
	const bundle = (coverage?: unknown) => ({ coverage }) as unknown as GlobalObjectData;

	it('reads the coverage block and nothing else', () => {
		expect(canBePlaced(bundle({ windows: [[1, 2]] }))).toBe(true);
		expect(canBePlaced(bundle({ windows: [] }))).toBe(false);
		// Sputnik 1: launch and decay dates, and no window.
		expect(canBePlaced(bundle())).toBe(false);
		expect(canBePlaced(null)).toBe(false);
	});
});
