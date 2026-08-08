import { describe, it, expect } from 'vitest';
import {
	arrivalCost,
	ascentDv,
	captureDv,
	circularSpeed,
	departureCost,
	injectionDv,
	parkingRadiusKm
} from './maneuvers';
import { EARTH, JUPITER, MARS, MOON } from './test-fixtures';

// Whether these figures match Earth, Apollo and Mars ascents is asserted in
// benchmarks.test.ts, which owns every published number and its tolerance.
describe('ascentDv', () => {
	it('ranks bodies by how hard they are to leave', () => {
		expect(ascentDv(MOON)).toBeLessThan(ascentDv(MARS));
		expect(ascentDv(MARS)).toBeLessThan(ascentDv(EARTH));
		expect(ascentDv(EARTH)).toBeLessThan(ascentDv(JUPITER));
	});
});

describe('injectionDv', () => {
	it('costs far less than the excess speed it buys, via the Oberth effect', () => {
		const vInf = 6;
		expect(injectionDv(EARTH.mu, parkingRadiusKm(EARTH), vInf)).toBeLessThan(vInf);
	});

	it('reduces to the escape burn when the excess speed is zero', () => {
		const r = parkingRadiusKm(EARTH);
		const expected = circularSpeed(EARTH.mu, r) * (Math.SQRT2 - 1);
		expect(injectionDv(EARTH.mu, r, 0)).toBeCloseTo(expected, 9);
	});
});

describe('captureDv', () => {
	it('is cheaper into a loose ellipse than into a circle', () => {
		const rp = parkingRadiusKm(MARS);
		const ellipse = captureDv(MARS.mu, rp, 20 * MARS.radiusKm, 2.65);
		const circle = captureDv(MARS.mu, rp, rp, 2.65);
		expect(ellipse).toBeLessThan(circle);
	});

	it('grows with arrival speed', () => {
		const rp = parkingRadiusKm(JUPITER);
		expect(captureDv(JUPITER.mu, rp, rp, 6)).toBeGreaterThan(captureDv(JUPITER.mu, rp, rp, 5));
	});
});

describe('arrivalCost', () => {
	it('charges nothing for a flyby', () => {
		const cost = arrivalCost(MARS, 3.2, 'flyby');
		expect(cost.captureKms).toBe(0);
		expect(cost.descentKms).toBe(0);
	});

	it('discounts capture at Mars for its atmosphere', () => {
		expect(arrivalCost(MARS, 2.65, 'capture').aerobraked).toBe(true);
		expect(arrivalCost(MOON, 2.65, 'capture').aerobraked).toBe(false);
	});

	it('makes landing on an airless body cost a full powered descent', () => {
		const moon = arrivalCost(MOON, 1.0, 'landing');
		expect(moon.descentKms).toBeGreaterThan(1.5);
		const mars = arrivalCost(MARS, 2.65, 'landing');
		// Mars descends on a heat shield and parachutes, so only touchdown is propulsive.
		expect(mars.descentKms).toBeLessThan(moon.descentKms);
	});

	it('orders the modes by cost', () => {
		const v = 2.65;
		const flyby = arrivalCost(MOON, v, 'flyby');
		const capture = arrivalCost(MOON, v, 'capture');
		const low = arrivalCost(MOON, v, 'low-orbit');
		const landing = arrivalCost(MOON, v, 'landing');
		const total = (c: { captureKms: number; descentKms: number }) => c.captureKms + c.descentKms;
		expect(total(flyby)).toBeLessThan(total(capture));
		expect(total(capture)).toBeLessThan(total(low));
		expect(total(low)).toBeLessThan(total(landing));
	});
});

describe('departureCost', () => {
	it('drops the ascent when departing from orbit', () => {
		const fromSurface = departureCost(EARTH, 3, 'surface');
		const fromOrbit = departureCost(EARTH, 3, 'orbit');
		expect(fromOrbit.ascentKms).toBe(0);
		expect(fromOrbit.injectionKms).toBeCloseTo(fromSurface.injectionKms, 12);
	});
});
