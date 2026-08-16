/**
 * The transfer family a trip inside one system is picked from, and the two
 * things that go wrong around it: a primary whose element row does not describe
 * its motion about the barycentre, and a guard that says so once per grid cell.
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { AU_KM } from '$lib/math/units';
import { SEC_PER_DAY } from './constants';
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

/**
 * A body held at a Lagrange point has no conic about its primary: Webb's fit
 * reads as a 126-day ellipse swinging between 0.6 and 1.5 million km, while
 * Webb stays out at L2. Since a same-system crossing is priced entirely on that
 * one distance, the separation has to be measured rather than propagated.
 */
describe('measured separation', () => {
	/** Holding 1.45 million km out and swinging round with the Earth, which is
	 *  what L2 looks like from here over a couple of months. */
	const HELD_KM = 1447500;
	const HELD_SPEED_KMS = 0.2;
	const STEP_DAYS = 2;

	function held(count: number) {
		const rate = (HELD_SPEED_KMS / HELD_KM) * SEC_PER_DAY;
		const jds: number[] = [];
		const r: [number, number, number][] = [];
		const v: [number, number, number][] = [];
		for (let i = 0; i < count; i++) {
			const angle = rate * STEP_DAYS * i;
			jds.push(J2000 + STEP_DAYS * i);
			r.push([HELD_KM * Math.cos(angle), HELD_KM * Math.sin(angle), 0]);
			v.push([-HELD_SPEED_KMS * Math.sin(angle), HELD_SPEED_KMS * Math.cos(angle), 0]);
		}
		return { centerId: EARTH_BARYCENTRIC.id, jds, r, v };
	}

	const HELD: TravelBody = {
		...MOON_BARYCENTRIC,
		id: 'probe-webb',
		// A fit that has it falling back towards Earth, which it never does.
		elements: { ...MOON_BARYCENTRIC.elements, a: 1061700 / AU_KM, e: 0.4506, ma: 231 },
		parentId: EARTH_BARYCENTRIC.id,
		samples: held(3)
	};

	it('reads the gap off the samples, not off the elements', () => {
		expect(separationKm(HELD, EARTH_BARYCENTRIC, J2000 + 1)).toBeCloseTo(HELD_KM, 0);
	});

	// The elements would have it at 700,000 km by then — half way in.
	it('is not fooled by an expired fit part way through', () => {
		const propagated = separationKm({ ...HELD, samples: undefined }, EARTH_BARYCENTRIC, J2000 + 4);
		expect(propagated).toBeLessThan(HELD_KM * 0.9);
		expect(separationKm(HELD, EARTH_BARYCENTRIC, J2000 + 4)).toBeCloseTo(HELD_KM, 0);
	});

	// Not a fallback to the elements: they are the fiction these replaced, and
	// reaching for them past the last date is how the far end lands half a
	// million km from the body. No answer means no trip is offered there.
	it('refuses beyond the last sample rather than propagating', () => {
		expect(separationKm(HELD, EARTH_BARYCENTRIC, J2000 + 10)).toBeNull();
	});

	// Samples about one body say nothing about the gap to another.
	it('ignores samples measured from somewhere else', () => {
		const elsewhere: TravelBody = {
			...HELD,
			samples: { ...HELD.samples!, centerId: 'naif-599' }
		};
		expect(separationKm(elsewhere, EARTH_BARYCENTRIC, J2000 + 1)).not.toBeCloseTo(HELD_KM, 0);
	});

	// The whole point: the family the grid is built from, and every arc in it,
	// now runs to where the body is rather than to where the fit says.
	it('bounds the transfer family on the measured gap', () => {
		const bounds = systemArcBounds(EARTH_BARYCENTRIC, HELD, J2000, J2000 + 4)!;
		const rNear = parkingRadiusKm(EARTH_BARYCENTRIC);
		expect(bounds.slowestDays).toBeCloseTo(hohmannArcDays(EARTH_BARYCENTRIC.mu, rNear, HELD_KM), 6);
	});
});

describe('offered routes', () => {
	// A polished candidate that stepped outside the grid on either axis would
	// leave the porkchop drawn from that grid with nowhere to mark the route it
	// just offered.
	it('keeps every route inside the grid it was drawn from', () => {
		const bounds = systemArcBounds(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, J2000, J2000 + 27)!;
		const options = {
			departFromJd: J2000,
			departToJd: J2000 + 27,
			tofMinDays: bounds.fastestDays,
			tofMaxDays: bounds.slowestDays,
			departSteps: 60,
			tofSteps: 60,
			systemPrimary: 'departure' as const
		};
		const grid = computePorkchop(EARTH_BARYCENTRIC, MOON_BARYCENTRIC, options);
		const routes = selectRoutes(grid, EARTH_BARYCENTRIC, MOON_BARYCENTRIC, options);

		expect(routes.length).toBeGreaterThan(0);
		for (const { route } of routes) {
			expect(route.departJd).toBeGreaterThanOrEqual(grid.departJds[0]);
			expect(route.departJd).toBeLessThanOrEqual(grid.departJds[grid.departSteps - 1]);
			expect(route.tofDays).toBeGreaterThanOrEqual(grid.tofDays[0]);
			expect(route.tofDays).toBeLessThanOrEqual(grid.tofDays[grid.tofSteps - 1]);
		}
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
