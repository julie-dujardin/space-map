import { describe, it, expect } from 'vitest';
import { buildConstantThrustRoute } from './brachistochrone';
import { SEC_PER_DAY } from './constants';
import { elementsToState } from './state';
import { norm, sub } from './vec3';
import { EARTH, J2000, MARS, MOON } from './test-fixtures';

/** A third of a gravity, the cruise every torch ship in fiction is flown at. */
const THIRD_G = 9.80665 / 3;
/** An ion drive: the same arc, four orders of magnitude slower. */
const ION = 0.002;

/** How far apart the two ends of a heliocentric trip are at a moment, km. */
function separationKm(jd: number): number {
	const from = elementsToState(EARTH.elements, jd)!;
	const to = elementsToState(MARS.elements, jd)!;
	return norm(sub(to.r, from.r));
}

describe('buildConstantThrustRoute', () => {
	it('crosses to Mars in the days a torch ship is written to take', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		expect(route).not.toBeNull();
		expect(route.constantThrust).toBe(THIRD_G);
		// Days rather than months, whatever the geometry. J2000 is close to the
		// worst of it — the two are 1.8 AU apart, on opposite sides of the Sun —
		// and a third of a gravity still crosses that inside a week.
		expect(route.tofDays).toBeGreaterThan(2);
		expect(route.tofDays).toBeLessThan(7);
	});

	it('holds the acceleration for the whole crossing', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		const burn = route.legs.filter((leg) => leg.kind === 'boost' || leg.kind === 'brake');
		const spent = burn.reduce((sum, leg) => sum + leg.dvKms, 0);
		// Δv is the acceleration times the time it is held, by definition.
		expect(spent).toBeCloseTo((THIRD_G / 1000) * route.tofDays * SEC_PER_DAY, 6);
		expect(burn.reduce((sum, leg) => sum + leg.days, 0)).toBeCloseTo(route.tofDays, 9);
		// Half of it spent stopping, so the flip is at half the total.
		expect(burn[0].dvKms).toBeCloseTo(burn[1].dvKms, 9);
	});

	it('arrives where the destination will be, not where it is', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		const seconds = route.tofDays * SEC_PER_DAY;
		const covered = ((THIRD_G / 1000) * seconds * seconds) / 4;
		const from = elementsToState(EARTH.elements, route.departJd)!;
		const to = elementsToState(MARS.elements, route.arriveJd)!;
		expect(covered).toBeCloseTo(norm(sub(to.r, from.r)), 3);
		// Mars has moved far enough over the crossing to matter.
		expect(covered).not.toBeCloseTo(separationKm(J2000), 3);
	});

	it('takes four times as long for a quarter of the acceleration', () => {
		const fast = buildConstantThrustRoute(EARTH, MOON, J2000, THIRD_G, {
			departureMode: 'orbit',
			systemPrimary: 'departure'
		})!;
		const slow = buildConstantThrustRoute(EARTH, MOON, J2000, THIRD_G / 16, {
			departureMode: 'orbit',
			systemPrimary: 'departure'
		})!;
		// t ∝ 1/√a, over a crossing short enough that the Moon barely moves.
		expect(slow.tofDays / fast.tofDays).toBeGreaterThan(3.9);
		expect(slow.tofDays / fast.tofDays).toBeLessThan(4.1);
	});

	it('is dominated by the drive for a torch and by the ends for an ion drive', () => {
		const torch = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		const ion = buildConstantThrustRoute(EARTH, MARS, J2000, ION, { departureMode: 'orbit' })!;
		// Months rather than days, which is what The Martian's Hermes flew.
		expect(ion.tofDays).toBeGreaterThan(100);
		expect(ion.tofDays).toBeLessThan(250);
		// The slower drive spends far less: Δv goes as √a for a fixed distance.
		expect(ion.totalDvKms).toBeLessThan(torch.totalDvKms / 10);
	});

	it('does not flip for a flyby, and screams past instead', () => {
		const stop = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit',
			arrivalMode: 'capture'
		})!;
		const past = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit',
			arrivalMode: 'flyby'
		})!;
		expect(past.legs.some((leg) => leg.kind === 'brake')).toBe(false);
		// Only accelerating covers the same ground in 1/√2 of the time.
		expect(past.tofDays).toBeLessThan(stop.tofDays);
		// And the ship is still going at everything the drive gave it.
		expect(past.vInfArrKms).toBeGreaterThan(stop.vInfArrKms * 10);
	});

	it('leaves at escape speed, so there is no launch energy to quote', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		expect(route.c3Km2S2).toBe(0);
		expect(route.vInfDepKms).toBe(0);
		// The arc is rest-to-rest, so what is left over on arrival is the two
		// bodies' orbital velocities differenced — tens of km/s between planets.
		expect(route.vInfArrKms).toBeGreaterThan(1);
	});

	it('lays out the same legs as any other route, and they sum', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'surface',
			arrivalMode: 'landing'
		})!;
		expect(route.legs.map((leg) => leg.kind)).toEqual([
			'ascent',
			'injection',
			'boost',
			'brake',
			'capture',
			'descent'
		]);
		expect(route.legs.reduce((sum, leg) => sum + leg.dvKms, 0)).toBeCloseTo(route.totalDvKms, 9);
		expect(route.legs.reduce((sum, leg) => sum + leg.days, 0)).toBeCloseTo(route.tofDays, 9);
		expect(route.totalDvKms - route.inSpaceDvKms).toBeCloseTo(route.legs[0].dvKms, 9);
	});

	it('reaches a body inside one system without a heliocentric arc', () => {
		const route = buildConstantThrustRoute(EARTH, MOON, J2000, THIRD_G, {
			departureMode: 'orbit',
			systemPrimary: 'departure'
		})!;
		expect(route).not.toBeNull();
		// A few hours at a third of a gravity, which is what 384 000 km costs.
		expect(route.tofDays).toBeGreaterThan(0.1);
		expect(route.tofDays).toBeLessThan(0.5);
	});

	it('refuses an acceleration that is not one', () => {
		expect(buildConstantThrustRoute(EARTH, MARS, J2000, 0)).toBeNull();
		expect(buildConstantThrustRoute(EARTH, MARS, J2000, -1)).toBeNull();
	});
});
