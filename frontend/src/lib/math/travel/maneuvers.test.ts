import { describe, it, expect } from 'vitest';
import {
	aeroPassRadiusKm,
	arrivalCampaignDays,
	arrivalCost,
	ascentDv,
	captureDv,
	circularSpeed,
	departureCost,
	injectionDv,
	periapsisSpeed,
	parkingOrbit,
	parkingRadiusKm
} from './maneuvers';
import { EARTH, JUPITER, MARS, MOON, SATURN, VENUS } from './test-fixtures';

// Whether these figures match Earth, Apollo and Mars ascents is asserted in
// benchmarks.test.ts, which owns every published number and its tolerance.
describe('ascentDv', () => {
	it('ranks bodies by how hard they are to leave', () => {
		expect(ascentDv(MOON)).toBeLessThan(ascentDv(MARS));
		expect(ascentDv(MARS)).toBeLessThan(ascentDv(EARTH));
		expect(ascentDv(EARTH)).toBeLessThan(ascentDv(JUPITER));
	});
});

/** Geostationary, and the loose ellipse a Mars orbiter enters. */
const GEO = { rPeriKm: 42164, rApoKm: 42164 };
const MARS_CAPTURE = { rPeriKm: parkingRadiusKm(MARS), rApoKm: 20 * MARS.radiusKm };

describe('an orbit named at either end', () => {
	// The fact the picker exists to show: a slow arrival is caught more cheaply
	// high up, because it has less of the well to fall down before the burn.
	it('is cheaper to enter high than low, at a modest arrival speed', () => {
		const vInf = 1.5;
		const high = arrivalCost(EARTH, vInf, 'low-orbit', 'none', GEO).captureKms;
		const low = arrivalCost(EARTH, vInf, 'low-orbit', 'none', parkingOrbit(EARTH)).captureKms;
		expect(high).toBeLessThan(low);
	});

	/**
	 * Which orbit is cheaper to leave from depends on how hard the trip is, and
	 * the two answers cross at about 8 km/s of excess speed for Earth. A gentle
	 * departure is bought more cheaply from high up, where there is less speed to
	 * make up; a violent one from low down, where the Oberth effect is largest.
	 * Both are shown to the reader, so both are pinned here.
	 */
	it('is cheaper to leave from high for a gentle departure, from low for a violent one', () => {
		const fromHigh = (vInf: number) => departureCost(EARTH, vInf, 'orbit', GEO).injectionKms;
		const fromLow = (vInf: number) =>
			departureCost(EARTH, vInf, 'orbit', parkingOrbit(EARTH)).injectionKms;
		expect(fromHigh(3)).toBeLessThan(fromLow(3));
		expect(fromLow(12)).toBeLessThan(fromHigh(12));
	});

	it('costs less to leave an ellipse than a circle of the same periapsis', () => {
		const vInf = 3;
		const ellipse = departureCost(MARS, vInf, 'orbit', MARS_CAPTURE).injectionKms;
		const circle = departureCost(MARS, vInf, 'orbit', parkingOrbit(MARS)).injectionKms;
		expect(ellipse).toBeLessThan(circle);
	});

	// A landing goes through the parking orbit whatever orbit was last asked for,
	// and a flyby enters none — so neither may be moved by one.
	it('is ignored by a landing and by a flyby', () => {
		const named = arrivalCost(MARS, 2.6, 'landing', 'none', GEO);
		const parked = arrivalCost(MARS, 2.6, 'landing');
		expect(named.captureKms).toBeCloseTo(parked.captureKms, 9);
		expect(named.descentKms).toBeCloseTo(parked.descentKms, 9);
		expect(arrivalCost(MARS, 2.6, 'flyby', 'none', GEO).captureKms).toBe(0);
	});

	it('reproduces the old cases when no orbit is named', () => {
		expect(arrivalCost(MARS, 2.6, 'capture').captureKms).toBeCloseTo(
			arrivalCost(MARS, 2.6, 'capture', 'none', MARS_CAPTURE).captureKms,
			9
		);
		expect(departureCost(EARTH, 3, 'orbit').injectionKms).toBeCloseTo(
			injectionDv(EARTH.mu, parkingRadiusKm(EARTH), 3),
			9
		);
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

describe('aeroPassRadiusKm', () => {
	// Derived from each body's own pressure and scale height: Mars comes out at
	// the 50 km the published post-pass burn was calibrated at, Venus deeper.
	it('places the pass where the envelope reaches the target pressure', () => {
		expect(aeroPassRadiusKm(MARS) - MARS.radiusKm).toBeCloseTo(50, 0);
		expect(aeroPassRadiusKm(VENUS) - VENUS.radiusKm).toBeCloseTo(76, 0);
	});

	// Saturn's derived interface sits over 400 km up — higher than the 200 km
	// parking convention every orbit here is quoted from, so the ceiling wins.
	it('keeps the pass under the parking convention on the deepest envelopes', () => {
		expect(aeroPassRadiusKm(SATURN) - SATURN.radiusKm).toBe(150);
	});

	it('floors at the Mars calibration when the envelope is thinner than the target', () => {
		const pluto = { ...MOON, aeroPressurePa: 1.15, aeroScaleHeightKm: 24 };
		expect(aeroPassRadiusKm(pluto) - pluto.radiusKm).toBe(50);
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

	// Mercury's exosphere and Io's volcanic wisp are measured readings, orders of
	// magnitude too thin for drag to repay a pass — a detection is not a brake.
	it('refuses a braking pass through an envelope too thin to matter', () => {
		const io = { ...MOON, aeroPressurePa: 3.3e-5 };
		expect(arrivalCost(io, 2.65, 'capture', 'aerocapture').aerobraked).toBe(false);
		// Pluto's ~1 Pa is the thinnest envelope with published aerocapture
		// studies, and it stays on the credited side of the line.
		const pluto = { ...MOON, aeroPressurePa: 1.15 };
		expect(arrivalCost(pluto, 2.65, 'capture', 'aerocapture').aerobraked).toBe(true);
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

	// What a search relies on to hold a whole grid to one deadline: the campaign
	// is a fact about the arrival, so an arc that comes in twice as fast still
	// spends the same months walking the orbit down.
	it('takes the same campaign however fast the approach is', () => {
		const days = arrivalCampaignDays(MARS, 'low-orbit', 'aerobraking');
		expect(days).toBeGreaterThan(60);
		for (const vInf of [0.5, 2.65, 9]) {
			expect(arrivalCost(MARS, vInf, 'low-orbit', 'aerobraking').aerobrakeDays).toBeCloseTo(
				days,
				9
			);
		}
	});

	it('has no campaign where the arrival flies no passes', () => {
		expect(arrivalCampaignDays(MARS, 'low-orbit', 'aerocapture')).toBe(0);
		expect(arrivalCampaignDays(MARS, 'low-orbit')).toBe(0);
		expect(arrivalCampaignDays(MOON, 'low-orbit', 'aerobraking')).toBe(0);
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
