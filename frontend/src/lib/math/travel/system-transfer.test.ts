/**
 * The transfer family a trip inside one system is picked from, and the two
 * things that go wrong around it: a primary whose element row does not describe
 * its motion about the barycentre, and a guard that says so once per grid cell.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { AU_KM } from '$lib/math/units';
import { EARTH_BARYCENTRIC, MOON_BARYCENTRIC, J2000 } from './test-fixtures';
import type { TravelBody } from './body';
import { computePorkchop, selectRoutes } from './porkchop';
import { parkingRadiusKm } from './maneuvers';
import { hohmannArcDays, separationKm, solveRadialArc, systemArcBounds } from './system-transfer';

const R_NEAR = parkingRadiusKm(EARTH_BARYCENTRIC);
const R_FAR = 384748;

afterEach(() => vi.restoreAllMocks());

describe('solveRadialArc', () => {
	it('answers at the Hohmann time itself, which is where a grid ends', () => {
		const slowest = hohmannArcDays(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR);
		expect(solveRadialArc(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR, slowest)).not.toBeNull();
	});

	it('has nothing slower than that — the half-ellipse is the slow end', () => {
		const slowest = hohmannArcDays(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR);
		expect(solveRadialArc(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR, slowest * 1.05)).toBeNull();
	});

	it('leaves the far end purely tangential on the slowest arc', () => {
		const slowest = hohmannArcDays(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR);
		const arc = solveRadialArc(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR, slowest)!;
		// Apoapsis: all of the speed is across the orbit, none along the radius.
		expect(arc.vFarRadialKms).toBeLessThan(1e-3);
		expect(arc.vFarTangentialKms).toBeGreaterThan(0.1);
	});

	it('climbs out faster as the arc is asked to be quicker', () => {
		const slowest = hohmannArcDays(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR);
		const slow = solveRadialArc(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR, slowest)!;
		const quick = solveRadialArc(EARTH_BARYCENTRIC.mu, R_NEAR, R_FAR, slowest * 0.5)!;
		expect(quick.vNearKms).toBeGreaterThan(slow.vNearKms);
		expect(quick.vFarRadialKms).toBeGreaterThan(slow.vFarRadialKms);
	});
});

describe('separation', () => {
	it('differences the pair, since both are described about their barycentre', () => {
		// Earth 4,674 km one way and the Moon 380,074 the other: neither number is
		// the gap, and their sum is.
		expect(separationKm(MOON_BARYCENTRIC, EARTH_BARYCENTRIC, J2000)).toBeCloseTo(R_FAR, 3);
	});

	// A planet's row can hold a degenerate fit — its position comes from sampled
	// ephemeris, and these numbers ride along. Earth's real one reads e≈1 with a
	// 17-minute period, which would fling it thousands of km per hour.
	it('seats a primary with no companion orbit at the barycentre', () => {
		const degenerate: TravelBody = {
			...EARTH_BARYCENTRIC,
			elements: { ...EARTH_BARYCENTRIC.elements, e: 0.9999981, n: 30122 }
		};
		const gap = separationKm(MOON_BARYCENTRIC, degenerate, J2000)!;
		// The Moon's own orbit about the barycentre, with nothing subtracted.
		expect(gap).toBeCloseTo(MOON_BARYCENTRIC.elements.a * AU_KM, 3);
	});
});

describe('reporting', () => {
	it('names an unusable primary once, not once per cell', () => {
		const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});
		const degenerate: TravelBody = {
			...EARTH_BARYCENTRIC,
			id: 'naif-399-degenerate',
			elements: { ...EARTH_BARYCENTRIC.elements, e: 0.9999981, n: 30122 }
		};
		const bounds = systemArcBounds(degenerate, MOON_BARYCENTRIC, J2000, J2000 + 27)!;
		const options = {
			departFromJd: J2000,
			departToJd: J2000 + 27,
			tofMinDays: bounds.fastestDays,
			tofMaxDays: bounds.slowestDays,
			departSteps: 40,
			tofSteps: 40,
			systemPrimary: 'departure' as const
		};
		const grid = computePorkchop(degenerate, MOON_BARYCENTRIC, options);
		selectRoutes(grid, degenerate, MOON_BARYCENTRIC, options);

		// Thousands of cells ask the same question. Answering it on the console
		// every time costs seconds with a debugger attached, which is what a solve
		// that never seems to finish actually was.
		expect(grid.solvedCount).toBeGreaterThan(100);
		expect(debug).toHaveBeenCalledTimes(1);
	});
});
