import { describe, it, expect } from 'vitest';
import {
	aeroPassRadiusKm,
	arrivalCampaignDays,
	arrivalCost,
	ascentDv,
	asymptoteTurnDeg,
	endOrbitNormal,
	captureDv,
	circularSpeed,
	combinedBurn,
	departureCost,
	injectionDv,
	orbitSpeedAtRadius,
	periapsisBurnWithTurn,
	periapsisSpeed,
	parkingOrbit,
	parkingRadiusKm,
	planeChangeDv,
	planeTiltPenaltyKms,
	planeTurnDeg
} from './maneuvers';
import { EARTH, JUPITER, MARS, MOON, SATURN, VENUS } from './test-fixtures';
import { dot, type Vec3 } from './vec3';

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

// Real pads, so the spread between them can be read against what launch
// operators say about their own latitudes.
const KOUROU_LAT = 5.24;
const CANAVERAL_LAT = 28.49;
const BAIKONUR_LAT = 45.96;
const VOSTOCHNY_LAT = 51.88;

describe('planeTiltPenaltyKms', () => {
	it('charges nothing at the equator and the whole surface speed at the pole', () => {
		expect(planeTiltPenaltyKms(EARTH, { latDeg: 0 })).toBeCloseTo(0, 12);
		// Earth's ground moves at 465 m/s under the equator; a polar launch keeps
		// none of it.
		expect(planeTiltPenaltyKms(EARTH, { latDeg: 90 })).toBeCloseTo(0.4646, 3);
	});

	it('grows with latitude, and is symmetric about the equator', () => {
		const kourou = planeTiltPenaltyKms(EARTH, { latDeg: KOUROU_LAT });
		const baikonur = planeTiltPenaltyKms(EARTH, { latDeg: BAIKONUR_LAT });
		expect(kourou).toBeLessThan(baikonur);
		// Kourou's whole advantage over Baikonur is about 140 m/s.
		expect(baikonur - kourou).toBeCloseTo(0.14, 2);
		expect(planeTiltPenaltyKms(EARTH, { latDeg: -BAIKONUR_LAT })).toBeCloseTo(baikonur, 12);
	});

	it('takes the steeper of the site and what the arc demands', () => {
		// An equatorial pad still pays for an arc that leaves out of the equator.
		const steepArc = planeTiltPenaltyKms(EARTH, { latDeg: 0, asymptoteTiltDeg: 60 });
		expect(steepArc).toBeCloseTo(planeTiltPenaltyKms(EARTH, { latDeg: 60 }), 12);
		// And an arc lying flat is no relief to a pad far from the equator.
		const flatArc = planeTiltPenaltyKms(EARTH, { latDeg: 60, asymptoteTiltDeg: 5 });
		expect(flatArc).toBeCloseTo(steepArc, 12);
	});

	it('is nothing at all on a body with no spin to lose, or with no site named', () => {
		expect(planeTiltPenaltyKms({ ...EARTH, spinRadPerSec: undefined }, { latDeg: 60 })).toBe(0);
		expect(planeTiltPenaltyKms(EARTH)).toBe(0);
	});

	it('is worth little on a slowly turning body', () => {
		// The Moon turns once a month, so where a lander leaves from is worth
		// metres per second rather than hundreds.
		expect(planeTiltPenaltyKms(MOON, { latDeg: 90 })).toBeLessThan(0.006);
	});
});

describe('ascentDv with a site', () => {
	it('leaves the calibrated figure alone when no site is named', () => {
		expect(ascentDv(EARTH, { latDeg: 0 })).toBeCloseTo(ascentDv(EARTH), 12);
	});

	it('makes a high-latitude pad dearer than an equatorial one', () => {
		const kourou = ascentDv(EARTH, { latDeg: KOUROU_LAT });
		const canaveral = ascentDv(EARTH, { latDeg: CANAVERAL_LAT });
		const vostochny = ascentDv(EARTH, { latDeg: VOSTOCHNY_LAT });
		expect(kourou).toBeLessThan(canaveral);
		expect(canaveral).toBeLessThan(vostochny);
		// Every pad is at least the equatorial figure the constants are fitted to.
		expect(kourou).toBeGreaterThanOrEqual(ascentDv(EARTH));
		// And none of them is dear enough to change what class of vehicle it takes.
		expect(vostochny - kourou).toBeLessThan(0.2);
	});
});

describe('landing at a site', () => {
	it('charges a powered descent the same spin an ascent is charged', () => {
		const equator = arrivalCost(MOON, 1, 'landing', 'none', undefined, { latDeg: 0 });
		const pole = arrivalCost(MOON, 1, 'landing', 'none', undefined, { latDeg: 90 });
		expect(pole.descentKms - equator.descentKms).toBeCloseTo(
			planeTiltPenaltyKms(MOON, { latDeg: 90 }),
			12
		);
	});

	it('charges an arrival under a parachute nothing for where it comes down', () => {
		// The air has already taken the speed the ground's own motion would have
		// been measured against.
		const equator = arrivalCost(MARS, 2.6, 'landing', 'aerocapture', undefined, { latDeg: 0 });
		const pole = arrivalCost(MARS, 2.6, 'landing', 'aerocapture', undefined, { latDeg: 90 });
		expect(pole.descentKms).toBeCloseTo(equator.descentKms, 12);
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

describe('a named plane', () => {
	const LEO = parkingOrbit(EARTH);

	it('owes nothing while it is free, or while nobody could compute the tilt', () => {
		expect(asymptoteTurnDeg(undefined, 30)).toBe(0);
		expect(asymptoteTurnDeg(LEO, 30)).toBe(0);
		expect(asymptoteTurnDeg({ ...LEO, incDeg: 10 }, undefined)).toBe(0);
		expect(planeTurnDeg(undefined, 45)).toBe(0);
		expect(planeTurnDeg(45, undefined)).toBe(0);
	});

	it('owes the shortfall to an asymptote it cannot lean far enough for', () => {
		expect(asymptoteTurnDeg({ ...LEO, incDeg: 10 }, 30)).toBeCloseTo(20, 12);
		expect(asymptoteTurnDeg({ ...LEO, incDeg: 51.6 }, 30)).toBe(0);
		// A retrograde orbit leans no further than its prograde mirror.
		expect(asymptoteTurnDeg({ ...LEO, incDeg: 150 }, 30)).toBe(0);
		expect(asymptoteTurnDeg({ ...LEO, incDeg: 170 }, 30)).toBeCloseTo(20, 12);
	});

	// A pole leaning 30° off the ecliptic's, met by an asymptote along the
	// ecliptic that therefore comes in 30° out of this body's equator — Saturn's
	// case, near enough, and the one a stationary orbit has to turn out of.
	const POLE: Vec3 = [0, -Math.sin(Math.PI / 6), Math.cos(Math.PI / 6)];
	const ASYMPTOTE: Vec3 = [0, 1, 0];
	const ARRIVAL_NORMAL: Vec3 = [0, 0, 1];
	const angleTo = (normal: Vec3, other: Vec3) =>
		(Math.acos(Math.min(1, Math.max(-1, dot(normal, other)))) * 180) / Math.PI;
	/** Inclination of the plane a normal names, degrees to the equator. */
	const incOf = (normal: Vec3) => angleTo(normal, POLE);
	/** How far the plane misses the asymptote by, degrees. */
	const missDeg = (normal: Vec3) => (Math.asin(Math.abs(dot(normal, ASYMPTOTE))) * 180) / Math.PI;

	it('leaves the plane where the craft arrives while the trip names none', () => {
		expect(endOrbitNormal(LEO, POLE, ASYMPTOTE, ARRIVAL_NORMAL)).toEqual(ARRIVAL_NORMAL);
		expect(endOrbitNormal({ ...LEO, incDeg: 0 }, undefined, ASYMPTOTE, ARRIVAL_NORMAL)).toEqual(
			ARRIVAL_NORMAL
		);
	});

	// The one that reads wrong on the map when it is missed: an orbit drawn in
	// the plane the craft flew in rather than the equator it has to hang over.
	it('lays a stationary orbit on the equator, whichever way the trip came in', () => {
		expect(endOrbitNormal({ ...LEO, incDeg: 0 }, POLE, ASYMPTOTE, ARRIVAL_NORMAL)).toEqual(POLE);
		expect(endOrbitNormal({ ...LEO, incDeg: 0 }, POLE, [0, 1, 0], [1, 0, 0])).toEqual(POLE);
		// Retrograde is the same plane flown the other way round.
		const back = endOrbitNormal({ ...LEO, incDeg: 180 }, POLE, ASYMPTOTE, ARRIVAL_NORMAL);
		expect(dot(back, POLE)).toBeCloseTo(-1, 12);
	});

	it('holds the asymptote in a plane leaning far enough to reach it', () => {
		for (const incDeg of [30, 45, 90, 135]) {
			const normal = endOrbitNormal({ ...LEO, incDeg }, POLE, ASYMPTOTE, ARRIVAL_NORMAL);
			expect(incOf(normal), `${incDeg}`).toBeCloseTo(incDeg, 6);
			expect(dot(normal, ASYMPTOTE), `${incDeg}`).toBeCloseTo(0, 12);
		}
	});

	// The plane the route was charged the shortfall for: 10° of lean against a
	// 30° asymptote leaves 20° owing, and the plane is the one tipped straight at
	// it, missing by exactly that.
	it('leans as near the asymptote as it can when it cannot hold it', () => {
		const normal = endOrbitNormal({ ...LEO, incDeg: 10 }, POLE, ASYMPTOTE, ARRIVAL_NORMAL);
		expect(incOf(normal)).toBeCloseTo(10, 6);
		expect(missDeg(normal)).toBeCloseTo(20, 6);
		expect(asymptoteTurnDeg({ ...LEO, incDeg: 10 }, 30)).toBeCloseTo(20, 6);
	});

	it('leans off the plane it is in when there is no asymptote to hold', () => {
		const normal = endOrbitNormal({ ...LEO, incDeg: 20 }, POLE, undefined, ARRIVAL_NORMAL);
		expect(incOf(normal)).toBeCloseTo(20, 6);
	});

	it('turns through 60° for the speed itself, and through 0° for free', () => {
		expect(planeChangeDv(7.67, 60)).toBeCloseTo(7.67, 12);
		expect(combinedBurn(7.67, 7.67, 0)).toBe(0);
		expect(combinedBurn(11, 7.67, 0)).toBeCloseTo(11 - 7.67, 12);
		expect(combinedBurn(7.67, 7.67, 90)).toBeCloseTo(7.67 * Math.SQRT2, 12);
	});

	it('makes the turn wherever it is cheaper: in the burn, or out at apoapsis', () => {
		const loose = { rPeriKm: parkingRadiusKm(EARTH), rApoKm: 20 * EARTH.radiusKm };
		const vBurn = periapsisSpeed(EARTH.mu, loose.rPeriKm, 3);
		const plain = periapsisBurnWithTurn(EARTH.mu, loose, vBurn, 0);
		const vApo = orbitSpeedAtRadius(EARTH.mu, loose, loose.rApoKm);
		// A wide turn walks out to the slow apoapsis; folding it into a burn made
		// at periapsis speed would cost several times as much.
		expect(periapsisBurnWithTurn(EARTH.mu, loose, vBurn, 40)).toBeCloseTo(
			plain + planeChangeDv(vApo, 40),
			12
		);
		// A sliver of a turn on a circular orbit hides in the burn itself,
		// second-order small — cheaper than even the slowest separate burn.
		const leo = parkingOrbit(EARTH);
		const vLeo = periapsisSpeed(EARTH.mu, leo.rPeriKm, 3);
		const plainLeo = periapsisBurnWithTurn(EARTH.mu, leo, vLeo, 0);
		const sliver = periapsisBurnWithTurn(EARTH.mu, leo, vLeo, 1);
		expect(sliver).toBeLessThan(plainLeo + planeChangeDv(circularSpeed(EARTH.mu, leo.rPeriKm), 1));
		expect(sliver - plainLeo).toBeLessThan(0.02);
	});

	it('prices the turn into the injection, except for a launch, which picks its plane', () => {
		const inOrbit = (turn: number) =>
			departureCost(EARTH, 3, 'orbit', LEO, undefined, turn).injectionKms;
		expect(inOrbit(30)).toBeGreaterThan(inOrbit(0));
		const launch = (turn: number) =>
			departureCost(EARTH, 3, 'surface', LEO, undefined, turn).injectionKms;
		expect(launch(30)).toBeCloseTo(launch(0), 12);
	});

	it('prices the turn into the capture, except for a landing, which never keeps the orbit', () => {
		const capture = (turn: number) =>
			arrivalCost(EARTH, 3, 'low-orbit', 'none', LEO, undefined, turn).captureKms;
		expect(capture(30)).toBeGreaterThan(capture(0));
		const landing = (turn: number) =>
			arrivalCost(EARTH, 3, 'landing', 'none', LEO, undefined, turn);
		expect(landing(30).captureKms).toBeCloseTo(landing(0).captureKms, 12);
		expect(landing(30).descentKms).toBeCloseTo(landing(0).descentKms, 12);
	});

	it('turns an aero arrival at its apoapsis, where it is nearly free', () => {
		const lmo = parkingOrbit(MARS);
		const arrive = (aero: 'aerocapture' | 'aerobraking', turn: number) =>
			arrivalCost(MARS, 3, 'low-orbit', aero, lmo, undefined, turn);
		for (const aero of ['aerocapture', 'aerobraking'] as const) {
			const turned = arrive(aero, 30);
			const flat = arrive(aero, 0);
			expect(turned.captureKms).toBeGreaterThan(flat.captureKms);
			// The engine pays for the turn; the air's share is untouched.
			expect(turned.absorbedKms).toBeCloseTo(flat.absorbedKms, 12);
			// Far cheaper than making the same turn down at circular speed.
			expect(turned.captureKms - flat.captureKms).toBeLessThan(
				planeChangeDv(circularSpeed(MARS.mu, lmo.rPeriKm), 30)
			);
		}
	});

	it('charges a retrograde plane more surface speed than the whole credit', () => {
		const penalty = (tilt: number) =>
			planeTiltPenaltyKms(EARTH, { latDeg: 0, asymptoteTiltDeg: tilt });
		expect(penalty(150)).toBeGreaterThan(penalty(90));
		const surface = (EARTH.spinRadPerSec ?? 0) * EARTH.radiusKm;
		expect(penalty(180)).toBeCloseTo(2 * surface, 12);
	});
});
