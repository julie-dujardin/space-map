import { describe, it, expect } from 'vitest';
import { buildConstantThrustRoute, solveConstantThrustArc } from './brachistochrone';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { heldDriveMissKm } from './held-drive';
import { elementsToState } from './state';
import { dot, norm, normalize, sub } from './vec3';
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

	// The whole point of integrating rather than assuming: the arc has to end up
	// where the destination is, not merely be timed as though it would.
	it('actually arrives, flown under the primary it crossed', () => {
		const solved = solveConstantThrustArc(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		const chord = norm(
			sub(
				elementsToState(MARS.elements, J2000 + solved.arc.totalSeconds / SEC_PER_DAY)!.r,
				elementsToState(EARTH.elements, J2000)!.r
			)
		);
		// Kilometres out of hundreds of millions.
		expect(heldDriveMissKm(solved.problem, solved.arc)!).toBeLessThan(chord * 1e-8);
		// And Mars moved far enough over the crossing that where it started is the
		// wrong answer.
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		expect(chord).not.toBeCloseTo(separationKm(J2000), 3);
		expect(route.tofDays).toBeCloseTo(solved.arc.totalSeconds / SEC_PER_DAY, 9);
	});

	// A straight line is what the seed assumes, not what the answer is.
	it('does not fly the chord it was seeded from', () => {
		const solved = solveConstantThrustArc(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit'
		})!;
		const from = elementsToState(EARTH.elements, J2000)!;
		const to = elementsToState(MARS.elements, J2000 + solved.arc.totalSeconds / SEC_PER_DAY)!;
		const chord = normalize(sub(to.r, from.r));
		// The drive leans off the chord to answer for the Earth's own motion and
		// the Sun's pull, so pointing straight down it would miss.
		expect(dot(solved.arc.thrustDir, chord)).toBeLessThan(0.9999);
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

	/** 2026-08-10, with Earth and Mars near conjunction and 1.9 AU apart. */
	const CONJUNCTION_JD = 2461262.5;

	// The Sun pulls about 0.0059 m/s² at 1 AU, three times what an ion drive
	// holds, so whether such a ship can cross at all is a question about the
	// geometry rather than about the drive. Where it cannot, there is no arc — a
	// plausible-looking number would be worse than none, and those craft want a
	// spiral, which is a different route.
	it('refuses a crossing the drive cannot close', () => {
		expect(
			buildConstantThrustRoute(EARTH, MARS, CONJUNCTION_JD, ION, { departureMode: 'orbit' })
		).toBeNull();
		// The same drive at a geometry it can manage is still offered one, and a
		// drive that outpushes the Sun is never in doubt.
		expect(
			buildConstantThrustRoute(EARTH, MARS, J2000, ION, { departureMode: 'orbit' })
		).not.toBeNull();
		expect(
			buildConstantThrustRoute(EARTH, MARS, CONJUNCTION_JD, THIRD_G, { departureMode: 'orbit' })
		).not.toBeNull();
	});
});

describe('coasting between the burns', () => {
	const flatOut = () =>
		buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, { departureMode: 'orbit' })!;
	const coasting = (coastFraction: number) =>
		buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit',
			coastFraction
		})!;

	it('flies the flat-out arc when nothing is asked of it', () => {
		expect(coasting(0)).toEqual(flatOut());
		expect(flatOut().legs.some((leg) => leg.kind === 'cruise')).toBe(false);
	});

	it('buys a longer crossing with less Δv', () => {
		const fast = flatOut();
		const gentle = coasting(1);
		expect(gentle.tofDays).toBeGreaterThan(fast.tofDays);
		expect(gentle.totalDvKms).toBeLessThan(fast.totalDvKms);
	});

	it('cuts the drive for exactly the coast it lays out', () => {
		const route = coasting(0.6);
		expect(route.legs.map((leg) => leg.kind)).toEqual([
			'injection',
			'boost',
			'cruise',
			'brake',
			'capture'
		]);
		const [boost, cruise, brake] = route.legs.slice(1, 4);
		// Both burns are the same length, and Δv is the acceleration times the time
		// it is actually held — which is now the trip minus the coast.
		expect(boost.days).toBeCloseTo(brake.days, 9);
		expect(cruise.dvKms).toBe(0);
		expect(boost.dvKms + brake.dvKms).toBeCloseTo(
			(THIRD_G / 1000) * (boost.days + brake.days) * SEC_PER_DAY,
			6
		);
		expect(route.legs.reduce((sum, leg) => sum + leg.days, 0)).toBeCloseTo(route.tofDays, 9);
	});

	it('still arrives, however long the drive is off', () => {
		for (const fraction of [0.25, 0.5, 1]) {
			const solved = solveConstantThrustArc(EARTH, MARS, J2000, THIRD_G, {
				departureMode: 'orbit',
				coastFraction: fraction
			})!;
			expect(solved.arc.coastSeconds).toBeGreaterThan(0);
			expect(heldDriveMissKm(solved.problem, solved.arc)!).toBeLessThan(1e3);
		}
	});

	// The straight-line model handed back the same closing speed whatever the
	// coast — the two bodies' orbital velocities differenced, and nothing else,
	// because a rest-to-rest chord has no other answer to give. A flown arc has
	// been falling the whole way, so what it turns up carrying depends on how long
	// it fell. Which way is geometry, not a rule: at this date the long coast
	// arrives faster, at a conjunction it arrives slower.
	it('arrives carrying what it actually picked up, not the orbital difference', () => {
		const naive = norm(
			sub(
				elementsToState(MARS.elements, coasting(1).arriveJd)!.v,
				elementsToState(EARTH.elements, J2000)!.v
			)
		);
		const speeds = [0, 0.5, 1].map((fraction) => coasting(fraction).vInfArrKms);
		expect(new Set(speeds.map((s) => s.toFixed(3))).size).toBe(3);
		expect(Math.abs(speeds[2] - naive)).toBeGreaterThan(1);
	});

	it('coasts a flyby too, and arrives that much slower for it', () => {
		const past = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit',
			arrivalMode: 'flyby',
			coastFraction: 1
		})!;
		expect(past.legs.some((leg) => leg.kind === 'brake')).toBe(false);
		expect(past.legs.some((leg) => leg.kind === 'cruise')).toBe(true);
		const straight = buildConstantThrustRoute(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit',
			arrivalMode: 'flyby'
		})!;
		expect(past.vInfArrKms).toBeLessThan(straight.vInfArrKms);
	});

	it('asks no more of the coast than the model can describe', () => {
		// Past the far end of the slider is the far end of the slider, and short of
		// its near end is the arc a drive held all the way flies.
		expect(coasting(4)).toEqual(coasting(1));
		expect(coasting(-1)).toEqual(flatOut());
	});

	// The frame's centre is the planet, not the Sun, so the cap has to be taken
	// against the planet's own pull or it comes out four orders of magnitude wrong.
	it('measures the cap against whatever the crossing goes round', () => {
		const route = buildConstantThrustRoute(EARTH, MOON, J2000, THIRD_G, {
			departureMode: 'orbit',
			systemPrimary: 'departure',
			coastFraction: 1
		})!;
		const cruise = route.legs.find((leg) => leg.kind === 'cruise')!;
		// Hours, on a crossing that takes hours. Earth's pull at lunar distance is
		// a thousandth of the Sun's at 1 AU, which would have allowed weeks.
		expect(cruise.days).toBeGreaterThan(0.2);
		expect(cruise.days).toBeLessThan(2);
	});

	// No drift budget to respect any more: the coast is a conic walked in closed
	// form, so a long one is exact rather than merely tolerable. What used to be
	// capped near a month now runs past it and still lands on the target.
	it('coasts past what a straight line could have described', () => {
		const solved = solveConstantThrustArc(EARTH, MARS, J2000, THIRD_G, {
			departureMode: 'orbit',
			coastFraction: 1
		})!;
		const end = solved.problem.target(J2000 + solved.arc.totalSeconds / SEC_PER_DAY)!;
		const depthKm = (norm(solved.problem.start.r) + norm(end.r)) / 2;
		const crossedKm = norm(sub(end.r, solved.problem.start.r));
		// What the straight-line model would have allowed: a coast whose free-fall
		// drift stayed a twentieth of the crossing.
		const oldCapSeconds = Math.sqrt((2 * 0.05 * crossedKm) / (GM_SUN_KM3_S2 / (depthKm * depthKm)));
		expect(solved.arc.coastSeconds).toBeGreaterThan(oldCapSeconds);
		expect(heldDriveMissKm(solved.problem, solved.arc)!).toBeLessThan(1e3);
	});
});
