import { describe, expect, it, vi } from 'vitest';
import type { GlobalObjectData, ObjectDetailData } from '$lib/fetch/objects/object-data';
import { tdbToUtc } from '$lib/time/jd';
import { canBePlaced, coverageOf, nearestCoveredJd, type CoverageWindow } from './coverage';

const detail = vi.hoisted(() => ({ global: null as unknown }));
vi.mock('$lib/fetch/objects/object-data', () => ({
	fetchObjectDetail: () => Promise.resolve(detail as ObjectDetailData)
}));
vi.mock('$lib/fetch/metadata', () => ({
	fetchMetadata: () => Promise.resolve({ position: { zones: {} } }),
	isDateSegmented: () => false,
	lastCoveredMs: () => 0,
	zoneLayers: () => []
}));

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

describe('coverageOf', () => {
	/** A discovery date (UTC) and the end of the last position file (TDB). */
	const GATE = 2460000.25;
	const FILE_END = 2460100.5;

	it('keeps a launch or discovery date and puts a file bound on the clock', async () => {
		detail.global = { coverage: { windows: [[GATE, FILE_END]] }, orbit: { scale: 'system' } };
		const windows = await coverageOf('spkid-1');
		expect(windows).toEqual([[GATE, tdbToUtc(FILE_END)]]);
		// An arrival from before the discovery lands after it.
		expect(nearestCoveredJd(windows, GATE - 10)!).toBeGreaterThan(GATE);
	});

	it('leaves the windows of a satellite placed from its TLE in UTC', async () => {
		detail.global = { coverage: { windows: [[GATE, FILE_END]] }, orbit: { scale: 'planet' } };
		expect(await coverageOf('norad_satcat-25544')).toEqual([[GATE, FILE_END]]);
	});
});
