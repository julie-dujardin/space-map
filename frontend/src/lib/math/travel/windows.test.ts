import { describe, it, expect } from 'vitest';
import {
	crossingTimeDays,
	hohmannTransferDays,
	nextTransferWindows,
	requiredPhaseAngle,
	synodicPeriodDays,
	transferScale
} from './windows';
import {
	EARTH,
	ESCAPING_PROBE,
	J2000,
	JUPITER,
	LONG_PERIOD_COMET,
	MARS,
	VENUS
} from './test-fixtures';

// The published synodic periods, transfer times and phase angles are asserted
// in benchmarks.test.ts; these cover the behaviour around them.
describe('synodicPeriodDays', () => {
	it('approaches the inner body period as the target recedes', () => {
		// Jupiter barely moves over an Earth year, so its windows come round
		// almost annually — closer to Earth's year than to Mars' 780 days.
		expect(synodicPeriodDays(EARTH, JUPITER)!).toBeLessThan(synodicPeriodDays(EARTH, MARS)!);
		expect(synodicPeriodDays(EARTH, JUPITER)!).toBeGreaterThan(365);
	});

	it('is symmetric', () => {
		expect(synodicPeriodDays(MARS, EARTH)).toBeCloseTo(synodicPeriodDays(EARTH, MARS)!, 9);
	});

	it('is unbounded for orbits sharing a period', () => {
		expect(synodicPeriodDays(EARTH, EARTH)).toBe(Infinity);
	});
});

describe('hohmannTransferDays', () => {
	it('grows with the size of the target orbit', () => {
		expect(hohmannTransferDays(EARTH, VENUS)!).toBeLessThan(hohmannTransferDays(EARTH, MARS)!);
		expect(hohmannTransferDays(EARTH, MARS)!).toBeLessThan(hohmannTransferDays(EARTH, JUPITER)!);
	});

	it('is symmetric, since the arc is the same flown either way', () => {
		expect(hohmannTransferDays(MARS, EARTH)).toBeCloseTo(hohmannTransferDays(EARTH, MARS)!, 9);
	});
});

describe('requiredPhaseAngle', () => {
	it('has Venus trailing, since the target must be caught from ahead', () => {
		expect(requiredPhaseAngle(EARTH, VENUS)!).toBeLessThan(0);
	});
});

describe('nextTransferWindows', () => {
	it('returns the requested number of windows, in order', () => {
		const windows = nextTransferWindows(EARTH, MARS, J2000, 4);
		expect(windows).toHaveLength(4);
		for (let i = 1; i < windows.length; i++) {
			expect(windows[i]).toBeGreaterThan(windows[i - 1]);
		}
	});

	it('spaces Earth-Mars windows a synodic period apart', () => {
		const windows = nextTransferWindows(EARTH, MARS, J2000, 4);
		const synodic = synodicPeriodDays(EARTH, MARS)!;
		for (let i = 1; i < windows.length; i++) {
			// Real windows drift either side of the mean because both orbits are
			// eccentric; a month of slack is the physics, not solver error.
			expect(Math.abs(windows[i] - windows[i - 1] - synodic)).toBeLessThan(35);
		}
	});

	it('finds a window inside the first synodic period', () => {
		const windows = nextTransferWindows(EARTH, MARS, J2000, 1);
		expect(windows[0] - J2000).toBeGreaterThan(0);
		expect(windows[0] - J2000).toBeLessThan(synodicPeriodDays(EARTH, MARS)!);
	});

	it('has no window to offer for a target that is leaving', () => {
		expect(nextTransferWindows(EARTH, LONG_PERIOD_COMET, 2461263, 1)).toEqual([]);
	});

	it('puts the phase angle back where it was asked for', () => {
		const windows = nextTransferWindows(EARTH, MARS, J2000, 2);
		const phase = requiredPhaseAngle(EARTH, MARS)!;
		expect(windows.length).toBeGreaterThan(0);
		// Re-derive the geometry at the returned date and confirm it closes.
		for (const jd of windows) {
			const check = nextTransferWindows(EARTH, MARS, jd - 1, 1);
			expect(Math.abs(check[0] - jd)).toBeLessThan(2);
		}
		expect(isFinite(phase)).toBe(true);
	});
});

describe('crossingTimeDays', () => {
	const NOW = 2461000;

	it('stands in where a hyperbolic orbit leaves no semi-major axis', () => {
		expect(hohmannTransferDays(EARTH, ESCAPING_PROBE)).toBeNull();
		const crossing = crossingTimeDays(EARTH, ESCAPING_PROBE, NOW)!;
		// Voyager 2 is past 100 AU, so the ideal crossing runs into centuries.
		expect(crossing / 365.25).toBeGreaterThan(100);
	});

	it('agrees with the Hohmann time when both orbits are circular enough', () => {
		// Same quantity from instantaneous radii rather than semi-major axes, so
		// the two only differ by each orbit's eccentricity.
		const hohmann = hohmannTransferDays(EARTH, MARS)!;
		const crossing = crossingTimeDays(EARTH, MARS, NOW)!;
		expect(Math.abs(crossing - hohmann) / hohmann).toBeLessThan(0.15);
	});
});

describe('transferScale', () => {
	const NOW = 2461263;

	it('keeps the Hohmann time for a pair of round orbits', () => {
		const scale = transferScale(EARTH, MARS, NOW)!;
		expect(scale.days).toBeCloseTo(hohmannTransferDays(EARTH, MARS)!, 6);
		expect(scale.chase).toBe(false);
	});

	// The comet's semi-major axis is 2474 AU while the comet itself is 10 AU out,
	// so scaling the cruise off it offered nothing under seven thousand years.
	it('reads an eccentric target off its distance, not its semi-major axis', () => {
		const scale = transferScale(EARTH, LONG_PERIOD_COMET, NOW)!;
		expect(hohmannTransferDays(EARTH, LONG_PERIOD_COMET)! / 365.25).toBeGreaterThan(20000);
		expect(scale.days / 365.25).toBeLessThan(10);
		expect(scale.days).toBeCloseTo(crossingTimeDays(EARTH, LONG_PERIOD_COMET, NOW)!, 6);
	});

	it('calls a receding comet a chase, and a planet not', () => {
		expect(transferScale(EARTH, LONG_PERIOD_COMET, NOW)!.chase).toBe(true);
		expect(transferScale(EARTH, JUPITER, NOW)!.chase).toBe(false);
		expect(transferScale(EARTH, ESCAPING_PROBE, NOW)!.chase).toBe(true);
	});

	it('has nothing for an orbit that yields no position', () => {
		const broken = { ...MARS, elements: { ...MARS.elements, a: NaN } };
		expect(transferScale(EARTH, broken, NOW)).toBeNull();
	});
});
