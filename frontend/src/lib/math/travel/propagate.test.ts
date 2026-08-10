import { describe, it, expect } from 'vitest';
import { propagateFull, propagateState } from './propagate';
import { elementsToState } from './state';
import { solveLambert } from './lambert';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { dot, norm, sub, type Vec3 } from './vec3';
import { EARTH, J2000, MARS } from './test-fixtures';

const EARTH_YEAR_SEC = 365.256363 * SEC_PER_DAY;

describe('propagateState', () => {
	it('walks Earth round its own orbit back to where it started', () => {
		const state = elementsToState(EARTH.elements, J2000, GM_SUN_KM3_S2)!;
		const after = propagateState(state.r, state.v, EARTH_YEAR_SEC, GM_SUN_KM3_S2)!;
		expect(after).not.toBeNull();
		// A sidereal year returns it to within a fraction of a percent of 1 AU of
		// travel; the residual is the fixture's own precision, not the solver's.
		expect(norm(sub(after, state.r))).toBeLessThan(1e6);
	});

	it('agrees with the element propagator across a quarter orbit', () => {
		const state = elementsToState(EARTH.elements, J2000, GM_SUN_KM3_S2)!;
		const quarter = EARTH_YEAR_SEC / 4;
		const walked = propagateState(state.r, state.v, quarter, GM_SUN_KM3_S2)!;
		const expected = elementsToState(EARTH.elements, J2000 + quarter / SEC_PER_DAY, GM_SUN_KM3_S2)!;
		expect(norm(sub(walked, expected.r)) / norm(expected.r)).toBeLessThan(1e-6);
	});

	it('runs backwards as readily as forwards', () => {
		const state = elementsToState(MARS.elements, J2000, GM_SUN_KM3_S2)!;
		const forward = propagateState(state.r, state.v, 100 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		const back = propagateState(state.r, state.v, -100 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		const expected = elementsToState(MARS.elements, J2000 - 100, GM_SUN_KM3_S2)!;
		expect(norm(sub(back, expected.r)) / norm(expected.r)).toBeLessThan(1e-6);
		// Distinct directions, so the sign is genuinely being read.
		expect(norm(sub(forward, back))).toBeGreaterThan(1e7);
	});

	it('lands a Lambert arc on the position it was solved to reach', () => {
		const tofDays = 260;
		const from = elementsToState(EARTH.elements, J2000, GM_SUN_KM3_S2)!;
		const to = elementsToState(MARS.elements, J2000 + tofDays, GM_SUN_KM3_S2)!;
		const arc = solveLambert(from.r, to.r, tofDays * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		const flown = propagateState(from.r, arc.v1, tofDays * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		// The two solvers are independent, so this closing is what says the arc
		// drawn is the arc priced.
		expect(norm(sub(flown, to.r)) / norm(to.r)).toBeLessThan(1e-6);
	});

	it('walks a strongly hyperbolic arc the whole way along', () => {
		// The arc joining two long-period comets hundreds of AU out: a = −9 AU with
		// r/a near −60. The elliptic starter lands an order of magnitude out here
		// and Newton then walks off into the sinh terms, which stalled the drawn
		// path partway across.
		const r: Vec3 = [-6.9e10, 3.4e10, 2.4e10];
		const v: Vec3 = [-3.6, 1.9, 1.3];
		const alpha = 2 / norm(r) - (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) / GM_SUN_KM3_S2;
		expect(norm(r) * alpha).toBeLessThan(-1);

		let previous = norm(r);
		for (let i = 1; i <= 120; i++) {
			const point = propagateState(r, v, (i / 120) * 6e9, GM_SUN_KM3_S2);
			expect(point).not.toBeNull();
			// Outbound on a hyperbola, so it only ever climbs.
			const radius = norm(point!);
			expect(radius).toBeGreaterThan(previous);
			previous = radius;
		}
	});

	it('handles a hyperbolic state', () => {
		// A little over escape speed at 1 AU, thrown sideways.
		const r = [1.495978707e8, 0, 0] as const;
		const escape = Math.sqrt((2 * GM_SUN_KM3_S2) / r[0]);
		const v = [0, escape * 1.2, 0] as const;
		const after = propagateState(r, v, 200 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
		expect(after).not.toBeNull();
		// It only ever gets further away.
		expect(norm(after)).toBeGreaterThan(norm(r));
	});

	it('refuses a state it cannot walk', () => {
		expect(propagateState([0, 0, 0], [1, 0, 0], 100, GM_SUN_KM3_S2)).toBeNull();
		expect(propagateState([1e8, 0, 0], [0, 30, 0], 100, 0)).toBeNull();
	});

	it('returns the position it was given for no elapsed time', () => {
		const state = elementsToState(EARTH.elements, J2000, GM_SUN_KM3_S2)!;
		expect(propagateState(state.r, state.v, 0, GM_SUN_KM3_S2)).toEqual(state.r);
	});

	describe('propagateFull', () => {
		const state = elementsToState(EARTH.elements, J2000, GM_SUN_KM3_S2)!;

		// The velocity is what a coasting craft hands to whatever burns next, so it
		// has to be the arc's own and not a difference quotient off two positions.
		it('conserves energy over a long walk', () => {
			const energy = (r: Vec3, v: Vec3) => dot(v, v) / 2 - GM_SUN_KM3_S2 / norm(r);
			const after = propagateFull(state.r, state.v, 250 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
			expect(after).not.toBeNull();
			const before = energy(state.r, state.v);
			expect(Math.abs((energy(after.r, after.v) - before) / before)).toBeLessThan(1e-10);
		});

		it('walks back to where it started', () => {
			const out = propagateFull(state.r, state.v, 120 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
			const back = propagateFull(out.r, out.v, -120 * SEC_PER_DAY, GM_SUN_KM3_S2)!;
			expect(norm(sub(back.r, state.r)) / norm(state.r)).toBeLessThan(1e-10);
			expect(norm(sub(back.v, state.v)) / norm(state.v)).toBeLessThan(1e-10);
		});

		it('agrees with the ephemeris it was seeded from', () => {
			const days = 90;
			const walked = propagateFull(state.r, state.v, days * SEC_PER_DAY, GM_SUN_KM3_S2)!;
			const direct = elementsToState(EARTH.elements, J2000 + days, GM_SUN_KM3_S2)!;
			// Mean elements are not a Kepler propagation of themselves, so this is a
			// sanity bound rather than an identity.
			expect(norm(sub(walked.r, direct.r)) / norm(direct.r)).toBeLessThan(1e-3);
			expect(norm(sub(walked.v, direct.v)) / norm(direct.v)).toBeLessThan(1e-3);
		});
	});
});
