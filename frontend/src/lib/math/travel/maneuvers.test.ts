import { describe, it, expect } from 'vitest';
import {
	arrivalCost,
	ascentDv,
	captureDv,
	circularSpeed,
	departureCost,
	injectionDv,
	periapsisSpeed,
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

	it('uses the atmosphere only where there is one and only when asked', () => {
		expect(arrivalCost(MARS, 2.65, 'capture').aerobraked).toBe(false);
		expect(arrivalCost(MARS, 2.65, 'capture', 'aerocapture').aerobraked).toBe(true);
		// Asking is not the same as receiving, which is what lets the request stand
		// while the destination changes.
		expect(arrivalCost(MOON, 2.65, 'capture', 'aerocapture').aerobraked).toBe(false);
	});

	it('makes landing on an airless body cost a full powered descent', () => {
		const moon = arrivalCost(MOON, 1.0, 'landing');
		expect(moon.descentKms).toBeGreaterThan(1.5);
		// Mars descends on a heat shield and parachutes, so only touchdown is
		// propulsive — but only for a craft that brought one.
		expect(arrivalCost(MARS, 2.65, 'landing', 'aerocapture').descentKms).toBeLessThan(
			moon.descentKms
		);
		expect(arrivalCost(MARS, 2.65, 'landing').descentKms).toBeGreaterThan(1.5);
	});

	it('prices an aerocapture as the burn that lifts periapsis back out', () => {
		const propulsive = arrivalCost(MARS, 2.65, 'low-orbit');
		const aero = arrivalCost(MARS, 2.65, 'low-orbit', 'aerocapture');
		// Real studies budget tens of m/s post-pass against a burn of km/s.
		expect(aero.captureKms).toBeLessThan(0.2);
		expect(aero.captureKms).toBeLessThan(propulsive.captureKms / 10);
		expect(aero.absorbedKms).toBeGreaterThan(1);
		// One pass, so there is nothing to wait for.
		expect(aero.aerobrakeDays).toBe(0);
		// The pass is flown below the parking orbit, so it is met faster than it.
		expect(aero.entrySpeedKms!).toBeGreaterThan(
			periapsisSpeed(MARS.mu, parkingRadiusKm(MARS), 2.65)
		);
	});

	it('prices aerobraking as an insertion burn plus months of passes', () => {
		const braked = arrivalCost(MARS, 2.65, 'low-orbit', 'aerobraking');
		const aero = arrivalCost(MARS, 2.65, 'low-orbit', 'aerocapture');

		// The engine still does the capture, so this is nowhere near a single pass.
		expect(braked.captureKms).toBeGreaterThan(aero.captureKms * 5);
		// ...but it is still cheaper than circularizing on the engine.
		expect(braked.captureKms).toBeLessThan(arrivalCost(MARS, 2.65, 'low-orbit').captureKms);
		// The four flown Mars campaigns removed 1.0-1.2 km/s over 2-10 months.
		expect(braked.absorbedKms).toBeGreaterThan(0.8);
		expect(braked.absorbedKms).toBeLessThan(1.6);
		expect(braked.aerobrakeDays).toBeGreaterThan(60);
		expect(braked.aerobrakeDays).toBeLessThan(300);
	});

	it('has nothing for aerobraking to do when the target is the capture ellipse', () => {
		const braked = arrivalCost(MARS, 2.65, 'capture', 'aerobraking');
		expect(braked.aerobrakeDays).toBe(0);
		expect(braked.captureKms).toBeCloseTo(arrivalCost(MARS, 2.65, 'capture').captureKms, 9);
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
