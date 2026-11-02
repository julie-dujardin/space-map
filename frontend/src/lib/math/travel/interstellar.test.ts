import { describe, it, expect } from 'vitest';
import { clockJd } from '$lib/math/orbit/position';
import { DAYS_PER_YEAR } from '$lib/time/jd';
import { AU_KM, LIGHT_YEAR_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { G0_M_S2, GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import {
	buildInterstellarCruiseRoute,
	buildInterstellarTorchRoute,
	coastShape,
	conicPlaceKm,
	crossingElapsed,
	crossingFlownKm,
	crossingIntegral,
	crossingStretches,
	crossingSweep,
	endPlaceKm,
	fastestCrossingEndJd,
	interstellarDrive,
	rapidityOfSpeed,
	speedOfRapidity,
	type InterstellarCruiseOptions,
	type InterstellarDrive,
	type RapidityRate,
	type SystemEnd
} from './interstellar';
import type { TravelBody } from './body';
import {
	arrivalCost,
	captureDv,
	departureCost,
	type ArrivalMode,
	type EndOrbit
} from './maneuvers';
import { routeEndJd, routeShipDays, type Route } from './route';
import { elementsToState } from './state';
import { EARTH, EUROPA, J2000, JUPITER, MARS, MOON } from './test-fixtures';
import { add, cross, dot, norm, normalize, scale, sub, type Vec3 } from './vec3';
import { checkFeasibility, type Vehicle } from './vehicles';

const C = SPEED_OF_LIGHT_KM_S;

/** Mean motion of a circle of `aAu` about a star of `mu`, degrees per day. */
function meanMotion(mu: number, aAu: number): number {
	return (Math.sqrt(mu / (aAu * AU_KM) ** 3) * SEC_PER_DAY * 180) / Math.PI;
}

/** A star `ly` light-years out along the x axis, met as the end itself. */
function starAt(ly: number, massSolar = 1): SystemEnd {
	return {
		body: {
			id: `x-${ly}`,
			mu: massSolar * GM_SUN_KM3_S2,
			muEstimated: true,
			radiusKm: 700_000,
			elements: { a: 0, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0, epoch: J2000 }
		},
		starKm: [ly * LIGHT_YEAR_KM, 0, 0],
		starMu: massSolar * GM_SUN_KM3_S2,
		atStar: true
	};
}

/** Proxima Centauri b about its star, 4.24 ly out. */
const PROXIMA_B: SystemEnd = {
	body: {
		id: 'x-27424668-b-1',
		mu: 1.07 * 398_600.4418,
		muEstimated: true,
		radiusKm: 6_500,
		elements: { a: 0.0485, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 360 / 11.186, epoch: J2000 }
	},
	starKm: [4.24 * LIGHT_YEAR_KM, 0, 0],
	starMu: 0.122 * GM_SUN_KM3_S2,
	atStar: false
};

const FROM_EARTH: SystemEnd = {
	body: EARTH,
	starKm: [0, 0, 0],
	starMu: GM_SUN_KM3_S2,
	atStar: false
};

function years(days: number): number {
	return days / DAYS_PER_YEAR;
}

function leg(route: Route, kind: string) {
	return route.legs.find((l) => l.kind === kind);
}

/** The rapidity figure that a coast is priced at, km/s. */
function hyperbolicKms(route: Route): number {
	return route.interstellar!.rapidityKms;
}

/** The closing speed at a planet, rebuilt from the drawn hyperbola and the state
 *  of the planet on the arrival date. */
function drawnClosingKms(route: Route, origin: SystemEnd, target: SystemEnd): number {
	const conic = coastShape(route, origin, target)!.arrival!;
	const met = elementsToState(target.body.elements, route.arriveJd)!;
	return norm(add(conic.v, met.v));
}

/** The excess speed at a body, rebuilt from the drawn hyperbola and its state on
 *  the departure date. */
function drawnExcessKms(route: Route, origin: SystemEnd, target: SystemEnd): number {
	const conic = coastShape(route, origin, target)!.departure!;
	const left = elementsToState(origin.body.elements, route.departJd)!;
	return norm(sub(conic.v, left.v));
}

describe('buildInterstellarTorchRoute', () => {
	it('takes Nostalgia for Infinity to Proxima in 3.53 years aboard and 5.87 on Earth', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		})!;
		expect(Math.abs(years(routeShipDays(route)) - 3.53)).toBeLessThan(0.02);
		expect(Math.abs(years(route.tofDays) - 5.87)).toBeLessThan(0.02);
		expect(route.peakSpeedKms! / C).toBeCloseTo(0.95, 2);
		expect(route.interstellar!.gamma).toBeCloseTo(
			1 / Math.sqrt(1 - (route.peakSpeedKms! / C) ** 2),
			9
		);
	});

	it('takes the Hail Mary to Tau Ceti in 3.9 years aboard and 13.1 on Earth', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(11.9), J2000, 1.5 * G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		})!;
		expect(Math.abs(years(routeShipDays(route)) - 3.9)).toBeLessThan(0.02);
		expect(Math.abs(years(route.tofDays) - 13.1)).toBeLessThan(0.05);
	});

	it('agrees with the Newtonian arc at low speed', () => {
		const accelMs2 = 0.01;
		const near = { ...starAt(0), starKm: [1e9, 0, 0] as [number, number, number] };
		const route = buildInterstellarTorchRoute(starAt(0), near, J2000, accelMs2, {
			departureMode: 'rendezvous',
			arrivalMode: 'rendezvous'
		})!;
		const { distanceKm } = route.interstellar!;
		const halfSeconds = Math.sqrt(distanceKm / (accelMs2 / 1000));
		expect(route.tofDays / ((2 * halfSeconds) / SEC_PER_DAY)).toBeCloseTo(1, 6);
		expect(leg(route, 'boost')!.dvKms / ((accelMs2 / 1000) * halfSeconds)).toBeCloseTo(1, 6);
		expect(routeShipDays(route) / route.tofDays).toBeCloseTo(1, 6);
	});

	it('spends less Δv and takes longer the more it coasts', () => {
		const at = (coastFraction: number) =>
			buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
				departureMode: 'orbit',
				arrivalMode: 'rendezvous',
				coastFraction
			})!;
		const routes = [at(0), at(0.25), at(1)];
		for (let i = 1; i < routes.length; i++) {
			expect(routes[i].totalDvKms).toBeLessThan(routes[i - 1].totalDvKms);
			expect(routes[i].tofDays).toBeGreaterThan(routes[i - 1].tofDays);
		}
		// The far end coasts six times as long as the flat-out crossing takes.
		expect(leg(routes[2], 'cruise')!.days / routes[0].tofDays).toBeCloseTo(6, 6);
		expect(leg(routes[0], 'cruise')).toBeUndefined();
	});

	it('burns all the way past a flyby and keeps its speed', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'flyby'
		})!;
		expect(leg(route, 'brake')).toBeUndefined();
		expect(route.vInfArrKms).toBe(route.peakSpeedKms);
		// One burn over the whole distance: cosh φ = 1 + a·D/c².
		const phi = Math.acosh(1 + ((G0_M_S2 / 1000) * route.interstellar!.distanceKm) / C ** 2);
		expect(route.peakSpeedKms! / C).toBeCloseTo(Math.tanh(phi), 9);
	});

	it('prices the ends as every other held arc does', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, PROXIMA_B, J2000, G0_M_S2, {
			departureMode: 'surface',
			arrivalMode: 'low-orbit'
		})!;
		expect(route.legs[0].kind).toBe('ascent');
		expect(leg(route, 'injection')!.dvKms).toBeCloseTo(
			departureCost(EARTH, 0, 'surface').injectionKms,
			9
		);
		expect(leg(route, 'capture')).toBeDefined();
		expect(route.constantThrust).toBe(G0_M_S2);
	});
});

describe('buildInterstellarCruiseRoute', () => {
	const MU = GM_SUN_KM3_S2;
	/** Speed on a circle of 1 au about the Sun, and the speed of escape there. */
	const CIRCLE_KMS = Math.sqrt(MU / AU_KM);
	const ESCAPE_KMS = Math.sqrt((2 * MU) / AU_KM);
	/** A body on a circle of 1 au in the ecliptic, at +x and moving along +y at J2000. */
	const FROM_CIRCLE: SystemEnd = {
		body: {
			...EARTH,
			elements: { a: 1, e: 0, i: 0, om: 0, w: 0, ma: 0, n: meanMotion(MU, 1), epoch: J2000 }
		},
		starKm: [0, 0, 0],
		starMu: MU,
		atStar: false
	};

	/** A star 4.24 ly from the body at J2000, along the unit vector `direction`. */
	function starToward(direction: Vec3): SystemEnd {
		const end = starAt(4.24);
		const from = endPlaceKm(FROM_CIRCLE, J2000);
		return { ...end, starKm: add(from, scale(direction, 4.24 * LIGHT_YEAR_KM)) };
	}

	/** Excess speed against the Sun after a burn along the circle's motion that
	 *  leaves it at `vInfKms`, and the angle from the burn to the asymptote. */
	function tangential(vInfKms: number): { cruiseKms: number; turn: number } {
		const cruiseKms = Math.sqrt((CIRCLE_KMS + vInfKms) ** 2 - ESCAPE_KMS ** 2);
		const e = 1 + (AU_KM * cruiseKms ** 2) / MU;
		return { cruiseKms, turn: Math.acos(-1 / e) };
	}

	const coast = (
		origin: SystemEnd,
		target: SystemEnd,
		drive: Exclude<InterstellarDrive, { kind: 'torch' }>,
		options: InterstellarCruiseOptions
	) => buildInterstellarCruiseRoute(origin, target, J2000, drive, options) as Route;

	it('leaves on the hyperbola about the Sun that points at the target star', () => {
		// A burn along the motion puts the periapsis at the body and the asymptote ν∞ on.
		const { cruiseKms, turn } = tangential(15);
		const route = coast(
			FROM_CIRCLE,
			starToward([Math.cos(turn), Math.sin(turn), 0]),
			{ kind: 'launch', c3Km2S2: 15 ** 2 },
			{ departureMode: 'orbit', arrivalMode: 'flyby' }
		);
		expect(hyperbolicKms(route)).toBeCloseTo(cruiseKms, 6);
		expect(route.vInfDepKms).toBeCloseTo(15, 6);
	});

	it('pays to cancel the motion of the body for a star straight out from the Sun', () => {
		// The path is a radial line, so the excess cancels the circular speed.
		const out = normalize(elementsToState(FROM_CIRCLE.body.elements, J2000)!.r);
		const route = coast(
			FROM_CIRCLE,
			starToward(out),
			{ kind: 'launch', c3Km2S2: 60 ** 2 },
			{ departureMode: 'orbit', arrivalMode: 'flyby' }
		);
		const cruiseKms = Math.sqrt(60 ** 2 - CIRCLE_KMS ** 2 - ESCAPE_KMS ** 2);
		expect(hyperbolicKms(route)).toBeCloseTo(cruiseKms, 6);
	});

	it('finds the best date in one orbit of the body', () => {
		const target = starToward([1, 0, 0]);
		const drive = { kind: 'launch', c3Km2S2: 15 ** 2 } as const;
		const options = { departureMode: 'orbit', arrivalMode: 'flyby' } as const;
		// At J2000 the star is straight out, and 15 km/s cannot cancel the motion.
		expect(buildInterstellarCruiseRoute(FROM_CIRCLE, target, J2000, drive, options)).toBe(
			'cannot-escape'
		);
		const best = coast(FROM_CIRCLE, target, drive, { ...options, launchWindow: true });
		// On the best date a burn along the motion points the asymptote at the star.
		const { cruiseKms, turn } = tangential(15);
		expect(hyperbolicKms(best)).toBeCloseTo(cruiseKms, 4);
		const days = (2 * Math.PI - turn) / ((meanMotion(MU, 1) * Math.PI) / 180);
		expect(Math.abs(best.departJd - (J2000 + days))).toBeLessThan(0.5);
	});

	it('costs more toward a star far from the plane of the orbit', () => {
		const drive = { kind: 'budget', dvKms: 30 } as const;
		const options = { departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true } as const;
		const inPlane = coast(FROM_CIRCLE, starToward([1, 0, 0]), drive, options);
		const tilt = Math.PI / 4;
		const tilted = coast(
			FROM_CIRCLE,
			starToward([Math.cos(tilt), 0, -Math.sin(tilt)]),
			drive,
			options
		);
		expect(tilted.interstellar!.cruiseKms).toBeLessThan(inPlane.interstellar!.cruiseKms / 2);
		// The whole budget goes into the departure burn on a flyby.
		expect(tilted.inSpaceDvKms).toBeCloseTo(30, 6);
		// A trip of tens of thousands of years is still a route.
		expect(years(tilted.tofDays)).toBeGreaterThan(20_000);
	});

	it('holds a planet with no period at its place, at the speed of its orbit', () => {
		const still = {
			...FROM_CIRCLE,
			body: { ...FROM_CIRCLE.body, elements: { ...FROM_CIRCLE.body.elements, n: 0 } }
		};
		const drive = { kind: 'budget', dvKms: 30 } as const;
		const options = { departureMode: 'orbit', arrivalMode: 'flyby' } as const;
		const target = starToward([0, 1, 0]);
		// The map keeps it still, so no date is better than another.
		const best = coast(still, target, drive, { ...options, launchWindow: true });
		expect(best.departJd).toBe(J2000);
		expect(best.interstellar!.cruiseKms).toBeCloseTo(
			coast(FROM_CIRCLE, target, drive, options).interstellar!.cruiseKms,
			3
		);
		expect(best.interstellar!.originKm).toEqual(endPlaceKm(still, J2000 + 100));
	});

	it('brakes into the orbit through 1 au that holds station at a star', () => {
		const route = coast(
			FROM_CIRCLE,
			starToward([1, 0, 0]),
			{ kind: 'budget', dvKms: 40 },
			{ departureMode: 'orbit', arrivalMode: 'rendezvous', launchWindow: true }
		);
		expect(route.inSpaceDvKms).toBeCloseTo(40, 6);
		const cruise = hyperbolicKms(route);
		// The target has one solar mass, so the speed of escape at 1 au is the Sun's.
		expect(leg(route, 'rendezvous')!.dvKms).toBeCloseTo(
			Math.hypot(cruise, ESCAPE_KMS) - ESCAPE_KMS,
			6
		);
		expect(rapidityOfSpeed(route.vInfArrKms)).toBeCloseTo(cruise, 6);
	});

	it('leaves a star from the same orbit through 1 au', () => {
		const route = coast(
			starAt(4.24),
			{ ...starAt(0), body: { ...starAt(0).body, id: 'naif-10' } },
			{ kind: 'budget', dvKms: 30 },
			{ departureMode: 'rendezvous', arrivalMode: 'rendezvous' }
		);
		// Both stars have one solar mass, so each pass spends half the budget.
		expect(leg(route, 'injection')!.dvKms).toBeCloseTo(15, 6);
		expect(leg(route, 'rendezvous')!.dvKms).toBeCloseTo(15, 6);
		expect(hyperbolicKms(route)).toBeCloseTo(
			Math.sqrt((ESCAPE_KMS + 15) ** 2 - ESCAPE_KMS ** 2),
			6
		);
		expect(rapidityOfSpeed(route.vInfDepKms)).toBeCloseTo(hyperbolicKms(route), 6);
	});

	it('prices the capture at a planet on the closing speed of its hyperbola', () => {
		const eccentric: SystemEnd = {
			...PROXIMA_B,
			body: { ...PROXIMA_B.body, elements: { ...PROXIMA_B.body.elements, e: 0.3 } }
		};
		const route = coast(
			FROM_CIRCLE,
			eccentric,
			{ kind: 'budget', dvKms: 60 },
			{ departureMode: 'orbit', arrivalMode: 'low-orbit', launchWindow: true }
		);
		expect(route.legs.map((l) => l.kind)).toEqual(['injection', 'cruise', 'capture']);
		const excess = rapidityOfSpeed(route.vInfArrKms);
		expect(excess).toBeCloseTo(drawnClosingKms(route, FROM_CIRCLE, eccentric), 3);
		expect(leg(route, 'capture')!.dvKms).toBeCloseTo(
			arrivalCost(PROXIMA_B.body, excess, 'low-orbit').captureKms,
			6
		);
	});

	it('meets a planet with an assumed orbit at its place, at the speed of that orbit', () => {
		const assumed: SystemEnd = {
			...PROXIMA_B,
			body: { ...PROXIMA_B.body, elements: { ...PROXIMA_B.body.elements, n: 0 } }
		};
		const route = coast(
			FROM_CIRCLE,
			assumed,
			{ kind: 'budget', dvKms: 60 },
			{ departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true }
		);
		const mu = PROXIMA_B.starMu!;
		const { elements } = PROXIMA_B.body;
		const held = { ...elements, n: meanMotion(mu, 0.0485) };
		const met = elementsToState(held, clockJd(elements, elements.epoch))!;
		const conic = coastShape(route, FROM_CIRCLE, assumed)!.arrival!;
		expect(rapidityOfSpeed(route.vInfArrKms)).toBeCloseTo(norm(add(conic.v, met.v)), 3);
	});

	it('refuses a craft that cannot leave the solar system', () => {
		expect(
			buildInterstellarCruiseRoute(
				FROM_EARTH,
				starAt(4.24),
				J2000,
				{ kind: 'budget', dvKms: 5 },
				{ departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true }
			)
		).toBe('cannot-escape');
	});

	it('refuses a craft that leaves but cannot also stop', () => {
		const options = { departureMode: 'orbit', launchWindow: true } as const;
		const drive = { kind: 'budget', dvKms: 15 } as const;
		expect(
			coast(FROM_CIRCLE, PROXIMA_B, drive, { ...options, arrivalMode: 'flyby' }).interstellar
		).toBeDefined();
		expect(
			buildInterstellarCruiseRoute(FROM_CIRCLE, PROXIMA_B, J2000, drive, {
				...options,
				arrivalMode: 'low-orbit'
			})
		).toBe('cannot-stop');
	});

	it('flies a launcher by on the energy of its curve, and never stops', () => {
		const at = (c3Km2S2: number, arrivalMode: ArrivalMode) =>
			buildInterstellarCruiseRoute(
				FROM_EARTH,
				starAt(4.24),
				J2000,
				{ kind: 'launch', c3Km2S2 },
				{ departureMode: 'surface', arrivalMode, launchWindow: true }
			);
		const flyby = at(158, 'flyby') as Route;
		expect(flyby.c3Km2S2).toBeCloseTo(158, 9);
		expect(flyby.interstellar!.cruiseKms).toBeGreaterThan(0);
		expect(at(158, 'rendezvous')).toBe('cannot-stop');
		expect(at(60, 'flyby')).toBe('cannot-escape');
	});

	// The budget is c times the rapidity it gains, so no budget passes c.
	it('stays below the speed of light on a budget of more than c', () => {
		const route = buildInterstellarCruiseRoute(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			{ kind: 'budget', dvKms: 400_000 },
			{ departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true }
		) as Route;
		const { cruiseKms, gamma, distanceKm } = route.interstellar!;
		expect(cruiseKms).toBeLessThan(C);
		expect(gamma).toBeCloseTo(1 / Math.sqrt(1 - (cruiseKms / C) ** 2), 9);
		// The pass at the star is 1 au short of its centre.
		expect(route.tofDays * SEC_PER_DAY).toBeGreaterThan((distanceKm - AU_KM) / C);
		expect(routeShipDays(route)).toBeCloseTo(route.tofDays / gamma, 6);
	});
});

// The feasibility check adds up the legs in its own order. A coast solved to the
// exact limit of the craft can then fail it by a rounding error.
describe('a coast at the limit of the craft', () => {
	/** Proxima b with eccentricity `e`, 4.24 ly out toward ecliptic longitude
	 *  `lonDeg` and latitude `latDeg`. */
	function planetToward(lonDeg: number, latDeg: number, e = 0): SystemEnd {
		const lon = (lonDeg * Math.PI) / 180;
		const lat = (latDeg * Math.PI) / 180;
		const direction: Vec3 = [
			Math.cos(lat) * Math.cos(lon),
			Math.cos(lat) * Math.sin(lon),
			Math.sin(lat)
		];
		return {
			...PROXIMA_B,
			body: { ...PROXIMA_B.body, elements: { ...PROXIMA_B.body.elements, e } },
			starKm: scale(direction, 4.24 * LIGHT_YEAR_KM)
		};
	}

	const TARGETS = [planetToward(0, 0), planetToward(130, -10, 0.15), planetToward(250, 5, 0.3)];

	const craft = (fields: Partial<Vehicle>): Vehicle =>
		({ id: 'c', kind: 'probe', propulsion: 'chemical', status: 'active', ...fields }) as Vehicle;

	it('keeps every coast on a Δv budget within the budget', () => {
		const failed: string[] = [];
		let routes = 0;
		for (let i = 0; i <= 30; i++) {
			const dvKms = 31.9 + i * 0.1;
			for (const arrivalMode of ['capture', 'low-orbit'] as const) {
				for (const target of TARGETS) {
					// A launch site and a tilted orbit split the legs as the panel does.
					const route = buildInterstellarCruiseRoute(
						FROM_EARTH,
						target,
						J2000,
						{ kind: 'budget', dvKms },
						{
							departureMode: 'surface',
							departureSiteLatDeg: 28.5,
							arrivalMode,
							targetOrbit: {
								rPeriKm: 6_900,
								rApoKm: arrivalMode === 'capture' ? 30_000 : 6_900,
								incDeg: 50
							},
							launchWindow: true
						}
					);
					if (route === null || typeof route === 'string') continue;
					routes++;
					// A coast to a planet slows just enough for the passage it picks.
					expect(route.inSpaceDvKms).toBeLessThanOrEqual(dvKms);
					expect(route.inSpaceDvKms / dvKms).toBeCloseTo(1, 4);
					const fit = checkFeasibility(craft({ dvKms }), route);
					if (fit.status !== 'ok')
						failed.push(`${dvKms.toFixed(1)} ${arrivalMode}: ${fit.marginKms}`);
				}
			}
		}
		expect(routes).toBeGreaterThan(100);
		expect(failed).toEqual([]);
	}, 60_000);

	it('flies every launcher within the top of its curve', () => {
		const failed: string[] = [];
		let routes = 0;
		for (let i = 0; i <= 30; i++) {
			const topC3 = 140 + i * 3.7;
			// No payload takes the top of the curve, where the payload is least.
			const launcher = craft({
				kind: 'launcher',
				c3Curve: {
					points: [
						[0, 9_000],
						[topC3 / 2, 3_000],
						[topC3, 400]
					],
					source: 'test',
					truncated: false
				}
			});
			const drive = interstellarDrive(launcher, 0) as Exclude<InterstellarDrive, { kind: 'torch' }>;
			for (const lonDeg of [0, 60, 120, 180, 240, 300]) {
				const route = buildInterstellarCruiseRoute(
					FROM_EARTH,
					planetToward(lonDeg, 0),
					J2000,
					drive,
					{
						departureMode: 'surface',
						arrivalMode: 'flyby',
						launchWindow: true
					}
				);
				if (route === null || typeof route === 'string') continue;
				routes++;
				expect(route.c3Km2S2).toBeLessThanOrEqual(topC3);
				expect(route.c3Km2S2 / topC3).toBeCloseTo(1, 4);
				const fit = checkFeasibility(launcher, route);
				if (fit.status !== 'ok') failed.push(`${topC3.toFixed(1)}: C3 ${route.c3Km2S2 - topC3}`);
			}
		}
		expect(routes).toBeGreaterThan(100);
		expect(failed).toEqual([]);
	});
});

describe('an end in the well of a planet', () => {
	const MU = GM_SUN_KM3_S2;
	const STAR = starAt(4.24);

	/** `moon` at the place of `planet` about the Sun, in the planet's well. */
	function moonEnd(moon: TravelBody, planet: TravelBody): SystemEnd {
		return {
			body: { ...moon, elements: planet.elements },
			starKm: [0, 0, 0],
			starMu: MU,
			atStar: false,
			wells: [{ mu: planet.mu, radiusKm: moon.elements.a * AU_KM }]
		};
	}

	function planetEnd(planet: TravelBody): SystemEnd {
		return { body: planet, starKm: [0, 0, 0], starMu: MU, atStar: false };
	}

	/** Excess speed against `moon` on a tangent pass, for `vInfKms` against `planet`. */
	function inside(moon: TravelBody, planet: TravelBody, vInfKms: number): number {
		const r = moon.elements.a * AU_KM;
		return Math.sqrt(vInfKms ** 2 + (2 * planet.mu) / r) - Math.sqrt(planet.mu / r);
	}

	const coast = (
		origin: SystemEnd,
		target: SystemEnd,
		drive: Exclude<InterstellarDrive, { kind: 'torch' }>,
		options: InterstellarCruiseOptions
	) => buildInterstellarCruiseRoute(origin, target, J2000, drive, options) as Route;

	const FLYBY = { departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true } as const;

	/** The coast of a launcher that leaves `planet` at `vInfKms`. */
	const launched = (planet: TravelBody, vInfKms: number) =>
		coast(planetEnd(planet), STAR, { kind: 'launch', c3Km2S2: vInfKms ** 2 }, FLYBY);

	it.each([
		['the Moon', MOON, EARTH, 40],
		['Europa', EUROPA, JUPITER, 30]
	])('flies by from %s as its planet does at the excess its well gives', (_, moon, planet, v) => {
		const dvKms = departureCost(moon, inside(moon, planet, v), 'orbit').injectionKms;
		const route = coast(moonEnd(moon, planet), STAR, { kind: 'budget', dvKms }, FLYBY);
		const fromPlanet = launched(planet, v);
		expect(route.interstellar!.cruiseKms).toBeCloseTo(fromPlanet.interstellar!.cruiseKms, 6);
		expect(rapidityOfSpeed(route.vInfDepKms)).toBeCloseTo(inside(moon, planet, v), 6);
		// The window spans one orbit of the planet.
		expect(route.departJd).toBeCloseTo(fromPlanet.departJd, 2);
	});

	it.each([
		['the Moon', MOON, EARTH, 40],
		['Europa', EUROPA, JUPITER, 30]
	])('stops at a star from %s on that budget and the brake', (_, moon, planet, v) => {
		const cruiseKms = hyperbolicKms(launched(planet, v));
		const leaveKms = departureCost(moon, inside(moon, planet, v), 'orbit').injectionKms;
		const brakeKms = captureDv(MU, AU_KM, Infinity, cruiseKms);
		const route = coast(
			moonEnd(moon, planet),
			STAR,
			{ kind: 'budget', dvKms: leaveKms + brakeKms },
			{ ...FLYBY, arrivalMode: 'rendezvous' }
		);
		expect(hyperbolicKms(route)).toBeCloseTo(cruiseKms, 6);
		expect(leg(route, 'injection')!.dvKms).toBeCloseTo(leaveKms, 6);
		expect(leg(route, 'rendezvous')!.dvKms).toBeCloseTo(brakeKms, 6);
	});

	it.each([
		['the Moon', MOON, EARTH],
		['Europa', EUROPA, JUPITER]
	])("falls down the planet's well to %s", (_, moon, planet) => {
		const target = moonEnd(moon, planet);
		const route = coast(
			STAR,
			target,
			{ kind: 'budget', dvKms: 80 },
			{ departureMode: 'rendezvous', arrivalMode: 'low-orbit' }
		);
		const excess = rapidityOfSpeed(route.vInfArrKms);
		const atPlanet = drawnClosingKms(route, STAR, target);
		expect(excess).toBeCloseTo(inside(moon, planet, atPlanet), 3);
		expect(leg(route, 'capture')!.dvKms).toBeCloseTo(
			arrivalCost(moon, excess, 'low-orbit').captureKms,
			6
		);
	});

	it("climbs out of the planet's well and falls into it under a held drive", () => {
		const out = buildInterstellarTorchRoute(moonEnd(MOON, EARTH), STAR, J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		})!;
		const escapeKms = inside(MOON, EARTH, 0);
		expect(out.vInfDepKms).toBeCloseTo(escapeKms, 6);
		expect(leg(out, 'injection')!.dvKms).toBeCloseTo(
			departureCost(MOON, escapeKms, 'orbit').injectionKms,
			9
		);
		const back = buildInterstellarTorchRoute(STAR, moonEnd(EUROPA, JUPITER), J2000, G0_M_S2, {
			departureMode: 'rendezvous',
			arrivalMode: 'low-orbit'
		})!;
		expect(leg(back, 'capture')!.dvKms).toBeCloseTo(
			arrivalCost(EUROPA, inside(EUROPA, JUPITER, 0), 'low-orbit').captureKms,
			9
		);
	});
});

/** A star of `massSolar` at `km`, met as the end itself. */
function starIn(km: Vec3, massSolar = 1): SystemEnd {
	return { ...starAt(0, massSolar), starKm: km };
}

/** A planet of `star` at `aAu`, on an orbit that is neither round nor flat. */
function planetOf(star: SystemEnd, aAu: number, extra: Partial<TravelBody['elements']> = {}) {
	const n = meanMotion(star.starMu!, aAu);
	const elements = { a: aAu, e: 0.1, i: 30, om: 40, w: 50, ma: 60, n, epoch: J2000, ...extra };
	const body = { id: `${star.body.id}-b`, mu: 4e5, muEstimated: true, radiusKm: 6_500, elements };
	return { ...star, body, atStar: false } as SystemEnd;
}

/** `moon` at the place of `planet` about the Sun, in the planet's well. */
function moonOf(moon: TravelBody, planet: TravelBody): SystemEnd {
	return {
		body: { ...moon, elements: planet.elements },
		starKm: [0, 0, 0],
		starMu: GM_SUN_KM3_S2,
		atStar: false,
		wells: [{ mu: planet.mu, radiusKm: moon.elements.a * AU_KM }]
	};
}

const coastOf = (
	origin: SystemEnd,
	target: SystemEnd,
	dvKms: number,
	options: InterstellarCruiseOptions = {}
) =>
	buildInterstellarCruiseRoute(
		origin,
		target,
		J2000,
		{ kind: 'budget', dvKms },
		{ departureMode: 'orbit', arrivalMode: 'low-orbit', launchWindow: true, ...options }
	) as Route;

/** The angle between two directions, degrees. */
const angleDeg = (a: Vec3, b: Vec3) => (Math.atan2(norm(cross(a, b)), dot(a, b)) * 180) / Math.PI;

describe('the place of an end', () => {
	const STAR = starIn([3e13, -2e13, 1e13], 0.8);
	const PLANET = planetOf(STAR, 0.5);

	it('is the star for a star', () => {
		expect(endPlaceKm(STAR, J2000)).toEqual(STAR.starKm);
	});

	it('is the star and the orbit about it for a planet', () => {
		const jd = J2000 + 1234.5;
		const { r } = elementsToState(PLANET.body.elements, jd)!;
		expect(endPlaceKm(PLANET, jd)).toEqual(add(STAR.starKm, r));
	});

	it('is the place of its planet for a moon', () => {
		expect(endPlaceKm(moonOf(MOON, EARTH), J2000)).toEqual(endPlaceKm(FROM_EARTH, J2000));
	});

	it.each([
		['known', STAR.starMu],
		['unknown', undefined]
	])('holds a planet with no period at its place at the epoch, μ %s', (_, starMu) => {
		const still = { ...planetOf(STAR, 2, { n: 0 }), starMu };
		const at = endPlaceKm(still, J2000);
		expect(endPlaceKm(still, J2000 + 1e6)).toEqual(at);
		const radius = norm(sub(at, STAR.starKm)) / AU_KM;
		expect(radius).toBeGreaterThan(2 * 0.9);
		expect(radius).toBeLessThan(2 * 1.1);
	});

	it('stays right past the range of a Date', () => {
		const n = PLANET.body.elements.n;
		const far = J2000 + (1e8 * 360) / n;
		expect(far).toBeGreaterThan(1e9);
		const shift = norm(sub(endPlaceKm(PLANET, far), endPlaceKm(PLANET, J2000)));
		expect(shift / AU_KM).toBeLessThan(1e-3);
	});
});

describe('a held arc between two bodies', () => {
	const options = { departureMode: 'orbit', arrivalMode: 'low-orbit' } as const;

	it('runs from the body at departure to the target at arrival', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, PROXIMA_B, J2000, G0_M_S2, options)!;
		const { originKm, targetKm, distanceKm } = route.interstellar!;
		expect(originKm).toEqual(endPlaceKm(FROM_EARTH, J2000));
		expect(norm(sub(targetKm, endPlaceKm(PROXIMA_B, route.arriveJd)))).toBeLessThan(1);
		expect(distanceKm).toBe(norm(sub(targetKm, originKm)));
	});

	it('settles the arrival date where the target moves far in the time', () => {
		const star = starIn([23 * AU_KM, 0, 0]);
		const target = planetOf(star, 1);
		const route = buildInterstellarTorchRoute(FROM_EARTH, target, J2000, 0.1, options)!;
		expect(route.tofDays).toBeGreaterThan(50);
		const { targetKm } = route.interstellar!;
		expect(norm(sub(targetKm, endPlaceKm(target, route.arriveJd)))).toBeLessThan(1);
	});
});

describe('a held arc at a star', () => {
	const FAR_KM = 4.24 * LIGHT_YEAR_KM;
	const SUN = starAt(0);
	const STAR = starAt(4.24);
	const hold = { departureMode: 'rendezvous', arrivalMode: 'rendezvous' } as const;
	const CIRCLE: EndOrbit = { rPeriKm: 5 * AU_KM, rApoKm: 5 * AU_KM };
	const held = (
		from: SystemEnd,
		to: SystemEnd,
		options: Parameters<typeof buildInterstellarTorchRoute>[4] = hold
	) => buildInterstellarTorchRoute(from, to, J2000, G0_M_S2, options)!;

	it('starts 1 au from the Sun on the line to the star, not at its centre', () => {
		const { originKm, targetKm, distanceKm } = held(SUN, STAR).interstellar!;
		expect(norm(sub(originKm, SUN.starKm))).toBeCloseTo(AU_KM, 3);
		expect(norm(cross(originKm, [1, 0, 0]))).toBe(0);
		expect(originKm[0]).toBeGreaterThan(0);
		expect(distanceKm).toBeCloseTo(norm(sub(targetKm, originKm)), 6);
	});

	it.each(['rendezvous', 'flyby'] as const)('stops 1 au short of a star on a %s', (arrivalMode) => {
		const route = held(FROM_EARTH, STAR, { departureMode: 'orbit', arrivalMode });
		const { originKm, targetKm } = route.interstellar!;
		expect(norm(sub(targetKm, STAR.starKm))).toBeCloseTo(AU_KM, 1);
		// On the line from the Earth to the star, on the Earth's side.
		const line = normalize(sub(STAR.starKm, originKm));
		expect(norm(sub(targetKm, sub(STAR.starKm, scale(line, AU_KM))))).toBeLessThan(0.1);
	});

	it('takes the distance and the dates from the shortened line', () => {
		const route = held(SUN, STAR);
		const { distanceKm, gamma } = route.interstellar!;
		expect(distanceKm).toBeCloseTo(FAR_KM - 2 * AU_KM, 0);
		// Half of a brachistochrone over that line: x = (c²/a)(cosh φ − 1).
		const accelKmS2 = G0_M_S2 / 1000;
		expect(gamma).toBeCloseTo(1 + (accelKmS2 * distanceKm) / 2 / C ** 2, 9);
		expect(crossingElapsed(route, distanceKm)!.days).toBeCloseTo(route.tofDays, 6);
		expect(crossingStretches(route)!.at(-1)!.toKm).toBe(distanceKm);
	});

	it('takes the Hail Mary from the Sun in 3.9 years aboard and 13.1 on Earth', () => {
		const route = buildInterstellarTorchRoute(SUN, starAt(11.9), J2000, 1.5 * G0_M_S2, hold)!;
		expect(Math.abs(years(routeShipDays(route)) - 3.9)).toBeLessThan(0.02);
		expect(Math.abs(years(route.tofDays) - 13.1)).toBeLessThan(0.05);
	});

	it('leaves the place of a planet end as it is', () => {
		const route = held(FROM_EARTH, STAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
		expect(route.interstellar!.originKm).toEqual(endPlaceKm(FROM_EARTH, J2000));
		const back = held(STAR, PROXIMA_B, { departureMode: 'rendezvous', arrivalMode: 'low-orbit' });
		expect(
			norm(sub(back.interstellar!.targetKm, endPlaceKm(PROXIMA_B, back.arriveJd)))
		).toBeLessThan(1);
	});

	it('stands off on the line to a planet at its place on the arrival date', () => {
		const star = starIn([40 * AU_KM, 0, 0]);
		const target = planetOf(star, 1);
		const route = held(SUN, target, { departureMode: 'rendezvous', arrivalMode: 'low-orbit' });
		const { originKm, targetKm } = route.interstellar!;
		expect(norm(originKm)).toBeCloseTo(AU_KM, 3);
		expect(norm(sub(targetKm, endPlaceKm(target, route.arriveJd)))).toBeLessThan(1);
		expect(norm(cross(normalize(originKm), normalize(targetKm)))).toBeLessThan(1e-9);
	});

	it('keeps the place of a star with an orbit, where the line stops at the ring', () => {
		const route = held(FROM_EARTH, STAR, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			targetOrbit: CIRCLE
		});
		expect(route.interstellar!.targetKm).toEqual(STAR.starKm);
		const leaving = held(STAR, SUN, {
			departureMode: 'orbit',
			departureOrbit: CIRCLE,
			arrivalMode: 'rendezvous'
		});
		expect(leaving.interstellar!.originKm).toEqual(STAR.starKm);
		expect(norm(sub(leaving.interstellar!.targetKm, SUN.starKm))).toBeCloseTo(AU_KM, 3);
	});

	it('stands off in any mode that leaves no orbit to stop at', () => {
		for (const options of [
			{ arrivalMode: 'rendezvous', targetOrbit: CIRCLE },
			{ arrivalMode: 'flyby', targetOrbit: CIRCLE },
			{ arrivalMode: 'landing', targetOrbit: CIRCLE },
			{ arrivalMode: 'low-orbit' },
			{ arrivalMode: 'capture' }
		] as const) {
			const { targetKm } = held(FROM_EARTH, STAR, options).interstellar!;
			expect(norm(sub(targetKm, STAR.starKm))).toBeCloseTo(AU_KM, 1);
		}
		for (const departureMode of ['rendezvous', 'surface'] as const) {
			const options = { departureMode, departureOrbit: CIRCLE };
			const { originKm } = held(STAR, SUN, options).interstellar!;
			expect(norm(sub(originKm, STAR.starKm))).toBeCloseTo(AU_KM, 1);
		}
	});

	it('stands off a star of unknown mass, whose orbit the route drops', () => {
		const unknown: SystemEnd = { ...STAR, starMu: undefined };
		const route = held(FROM_EARTH, unknown, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			targetOrbit: CIRCLE
		});
		expect(route.targetOrbit).toBeUndefined();
		expect(norm(sub(route.interstellar!.targetKm, unknown.starKm))).toBeCloseTo(AU_KM, 1);
	});

	describe('between two close stars', () => {
		it.each([0.02, 1, 3.99])('keeps the ends apart and in order %f au apart', (gapAu) => {
			const near = starIn([gapAu * AU_KM, 0, 0]);
			const { originKm, targetKm, distanceKm } = held(SUN, near).interstellar!;
			expect(originKm[0]).toBeCloseTo(gapAu * AU_KM * 0.25, 3);
			expect(near.starKm[0] - targetKm[0]).toBeCloseTo(gapAu * AU_KM * 0.25, 3);
			expect(targetKm[0]).toBeGreaterThan(originKm[0]);
			expect(distanceKm).toBeCloseTo(gapAu * AU_KM * 0.5, 3);
		});

		it('takes the whole hold from 4 au', () => {
			const near = starIn([4 * AU_KM, 0, 0]);
			expect(held(SUN, near).interstellar!.distanceKm).toBeCloseTo(2 * AU_KM, 3);
		});

		it('caps the stand-off by the distance to a planet, not by the two stars', () => {
			const near = starIn([3 * AU_KM, 0, 0]);
			// The planet has a place between the two stars, 0.2 au from the star left.
			const planet = planetOf(near, 2.8, { e: 0, i: 0, om: 0, w: 0, ma: 180, n: 0 });
			const route = held(SUN, planet, { departureMode: 'rendezvous', arrivalMode: 'low-orbit' });
			const { originKm, targetKm } = route.interstellar!;
			const gapKm = norm(endPlaceKm(planet, route.arriveJd));
			expect(gapKm).toBeCloseTo(0.2 * AU_KM, -3);
			expect(norm(originKm)).toBeCloseTo(gapKm / 4, 3);
			expect(norm(sub(targetKm, originKm))).toBeCloseTo((3 * gapKm) / 4, 3);
		});
	});

	describe('at a giant', () => {
		const RADIUS_KM = 7.9 * AU_KM;
		const sized = (star: SystemEnd, radiusKm = RADIUS_KM): SystemEnd => ({
			...star,
			body: { ...star.body, radiusKm }
		});
		const GIANT = sized(STAR);
		const FROM_ORBIT = { departureMode: 'orbit' } as const;

		it.each(['rendezvous', 'flyby'] as const)('stops 2 radii short on a %s', (arrivalMode) => {
			const { originKm, targetKm } = held(FROM_EARTH, GIANT, {
				...FROM_ORBIT,
				arrivalMode
			}).interstellar!;
			// On the line from the Earth to the star, on the Earth's side.
			const line = normalize(sub(GIANT.starKm, originKm));
			const stop = sub(GIANT.starKm, scale(line, 2 * RADIUS_KM));
			expect(norm(sub(targetKm, stop))).toBeLessThan(0.1);
		});

		it('starts 2 radii out from a giant it leaves', () => {
			const route = held(GIANT, FROM_EARTH, { departureMode: 'rendezvous', arrivalMode: 'flyby' });
			const { originKm, targetKm } = route.interstellar!;
			const line = normalize(sub(targetKm, GIANT.starKm));
			expect(norm(sub(originKm, add(GIANT.starKm, scale(line, 2 * RADIUS_KM))))).toBeLessThan(0.1);
		});

		it('takes the longer line of a giant into the distance and the dates', () => {
			const near = held(SUN, sized(STAR, 0.1 * AU_KM));
			const route = held(SUN, GIANT);
			expect(near.interstellar!.distanceKm - route.interstellar!.distanceKm).toBeCloseTo(
				(2 * 7.9 - 1) * AU_KM,
				0
			);
			expect(route.tofDays).toBeLessThan(near.tofDays);
		});

		it('keeps 1 au at a star of up to half an au', () => {
			const star = sized(STAR, 0.5 * AU_KM);
			const route = held(SUN, star);
			expect(norm(sub(route.interstellar!.targetKm, star.starKm))).toBeCloseTo(AU_KM, 1);
			expect(route).toEqual(held(SUN, sized(STAR, 1000)));
		});

		it('keeps the cap between two close stars', () => {
			const near = sized(starIn([20 * AU_KM, 0, 0]));
			const { targetKm } = held(SUN, near).interstellar!;
			expect(near.starKm[0] - targetKm[0]).toBeCloseTo(5 * AU_KM, 3);
		});

		it('leaves the ring of an orbit at a giant where it is', () => {
			const route = held(FROM_EARTH, GIANT, {
				...FROM_ORBIT,
				arrivalMode: 'low-orbit',
				targetOrbit: { rPeriKm: 20 * AU_KM, rApoKm: 20 * AU_KM }
			});
			expect(norm(sub(route.interstellar!.targetKm, GIANT.starKm))).toBe(0);
		});
	});
});

describe('a coast at a giant', () => {
	const RADIUS_KM = 7.9 * AU_KM;
	const MU = 20 * GM_SUN_KM3_S2;
	const STAR = starAt(4.24, 20);
	const GIANT: SystemEnd = { ...STAR, body: { ...STAR.body, radiusKm: RADIUS_KM } };

	it('brakes into the hold at 2 radii', () => {
		const route = coastOf(FROM_EARTH, GIANT, 60, { arrivalMode: 'rendezvous' });
		const excessKms = rapidityOfSpeed(route.vInfArrKms);
		expect(leg(route, 'rendezvous')!.dvKms).toBeCloseTo(
			captureDv(MU, 2 * RADIUS_KM, Infinity, excessKms),
			9
		);
	});

	it.each(['rendezvous', 'flyby'] as const)('meets a giant at 2 radii on a %s', (arrivalMode) => {
		const route = coastOf(FROM_EARTH, GIANT, 60, { arrivalMode });
		expect(norm(coastShape(route, FROM_EARTH, GIANT)!.arrival!.r)).toBeCloseTo(2 * RADIUS_KM, 3);
	});

	it('leaves a giant from the hold at 2 radii', () => {
		const route = coastOf(GIANT, FROM_EARTH, 60, {
			departureMode: 'rendezvous',
			arrivalMode: 'flyby'
		});
		expect(norm(coastShape(route, GIANT, FROM_EARTH)!.departure!.r)).toBeCloseTo(2 * RADIUS_KM, 3);
		expect(leg(route, 'injection')!.dvKms).toBeCloseTo(
			captureDv(MU, 2 * RADIUS_KM, Infinity, rapidityOfSpeed(route.vInfDepKms)),
			9
		);
	});

	it('takes the 1 au hold at a star of up to half an au', () => {
		const star: SystemEnd = { ...STAR, body: { ...STAR.body, radiusKm: 0.5 * AU_KM } };
		expect(coastOf(FROM_EARTH, star, 60, { arrivalMode: 'rendezvous' })).toEqual(
			coastOf(FROM_EARTH, STAR, 60, { arrivalMode: 'rendezvous' })
		);
	});
});

describe('a held arrival at a body with air', () => {
	const STAR = starAt(4.24);
	const FROM_STAR = { departureMode: 'rendezvous' } as const;
	const held = (target: SystemEnd, options: Parameters<typeof buildInterstellarTorchRoute>[4]) =>
		buildInterstellarTorchRoute(STAR, target, J2000, G0_M_S2, { ...FROM_STAR, ...options })!;
	const stops = ['low-orbit', 'capture', 'landing'] as const;

	describe.each(['aerocapture', 'aerobraking'] as const)('asked for %s', (aero) => {
		it.each(stops)('lists and prices no pass on a stop in %s', (arrivalMode) => {
			const asked = held(FROM_EARTH, { arrivalMode, aero });
			const engine = held(FROM_EARTH, { arrivalMode, aero: 'none' });
			expect(asked.legs).toEqual(engine.legs);
			expect(asked.totalDvKms).toBe(engine.totalDvKms);
			expect(asked.entrySpeedKms).toBeUndefined();
			expect(asked.legs.some((step) => step.aerobraked)).toBe(false);
		});
	});

	it('keeps the pass at a moon with air, which it meets at a speed', () => {
		const titan = moonOf({ ...MOON, aeroPressurePa: 146_700 }, EARTH);
		const route = held(titan, { arrivalMode: 'low-orbit', aero: 'aerocapture' });
		expect(leg(route, 'aero-pass')).toBeDefined();
	});

	it('keeps the pass of a coast, which meets the planet at a speed', () => {
		const route = coastOf(STAR, FROM_EARTH, 300, {
			...FROM_STAR,
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		});
		expect(leg(route, 'aero-pass')).toBeDefined();
	});
});

describe('a coast on its two hyperbolas', () => {
	const STAR = starIn([4.24 * LIGHT_YEAR_KM, 0, 0], 0.122);
	const PLANET = planetOf(STAR, 0.0485);
	const route = coastOf(FROM_EARTH, PLANET, 80);
	const shape = coastShape(route, FROM_EARTH, PLANET)!;
	const crossing = route.interstellar!;
	const line = sub(shape.lineToKm, shape.lineFromKm);

	it('leaves the body on the hyperbola that it prices', () => {
		const body = elementsToState(EARTH.elements, route.departJd)!;
		const conic = shape.departure!;
		expect(conic.r).toEqual(body.r);
		expect(norm(sub(conic.v, body.v)) / rapidityOfSpeed(route.vInfDepKms)).toBeCloseTo(1, 6);
		const excess = Math.sqrt(dot(conic.v, conic.v) - (2 * conic.mu) / norm(conic.r));
		expect(excess / crossing.cruiseKms).toBeCloseTo(1, 6);
	});

	it('walks each hyperbola from its end to the join in the time it gives', () => {
		for (const conic of [shape.departure!, shape.arrival!]) {
			const join = conicPlaceKm(conic, conic.seconds);
			expect(norm(sub(join, conic.joinKm)) / AU_KM).toBeLessThan(1e-6);
			expect(norm(sub(conic.joinKm, conic.starKm)) / AU_KM).toBeCloseTo(1000, 6);
		}
		expect(norm(sub(conicPlaceKm(shape.departure!, 0), crossing.originKm))).toBeLessThan(1e-6);
		expect(norm(sub(conicPlaceKm(shape.arrival!, 0), crossing.targetKm))).toBeLessThan(0.1);
	});

	it('joins the line along its way, with no turn', () => {
		const out = shape.departure!;
		const fall = shape.arrival!;
		const walk = (conic: typeof out) => {
			const before = conicPlaceKm(conic, conic.seconds - 1e6);
			return sub(conic.joinKm, before);
		};
		expect(angleDeg(walk(out), line)).toBeLessThan(0.01);
		expect(angleDeg(scale(walk(fall), -1), line)).toBeLessThan(0.01);
	});

	it('counts the time in the two wells', () => {
		const { conics, cruiseKms } = crossing;
		const lineDays = norm(line) / cruiseKms / SEC_PER_DAY;
		expect((conics!.departure.days + lineDays + conics!.arrival.days) / route.tofDays).toBeCloseTo(
			1,
			9
		);
		// A climb of 1000 au takes decades at 66 km/s.
		expect(conics!.departure.days / DAYS_PER_YEAR).toBeGreaterThan(50);
		expect(conics!.arrival.days / DAYS_PER_YEAR).toBeGreaterThan(50);
		expect(leg(route, 'cruise')!.days).toBe(route.tofDays);
	});

	it('meets the planet at its place on the arrival date', () => {
		expect(route.arriveJd).toBe(route.departJd + route.tofDays);
		expect(crossing.targetKm).toEqual(endPlaceKm(PLANET, route.arriveJd));
		expect(norm(sub(shape.arrival!.r, sub(crossing.targetKm, STAR.starKm)))).toBeLessThan(0.1);
	});

	it('leaves just under its fastest speed to make that date', () => {
		expect(route.inSpaceDvKms).toBeLessThan(80);
		expect(route.inSpaceDvKms / 80).toBeCloseTo(1, 3);
		const earliest = coastOf(FROM_EARTH, PLANET, 80 * (1 + 1e-3));
		expect(earliest.tofDays).toBeLessThan(route.tofDays);
	});

	it('takes no detour for a star, and spends all it has', () => {
		const stop = coastOf(FROM_EARTH, STAR, 60, { arrivalMode: 'rendezvous' });
		expect(stop.inSpaceDvKms / 60).toBeCloseTo(1, 9);
		const pass = coastShape(stop, FROM_EARTH, STAR)!.arrival!;
		expect(norm(pass.r) / AU_KM).toBeCloseTo(1, 9);
		expect(dot(pass.r, pass.v) / (norm(pass.r) * norm(pass.v))).toBeCloseTo(0, 9);
		expect(stop.interstellar!.targetKm).toEqual(STAR.starKm);
	});

	it('meets a planet with no period at the one place it has', () => {
		const still = planetOf(STAR, 0.2, { n: 0, e: 0 });
		const trip = coastOf(FROM_EARTH, still, 80);
		expect(trip.interstellar!.targetKm).toEqual(endPlaceKm(still, J2000));
		expect(trip.inSpaceDvKms / 80).toBeCloseTo(1, 9);
	});

	it('flies a planet with no orbit and a star of no known mass in a straight line', () => {
		const lost = { ...planetOf(STAR, 0.2, { n: 0 }), starMu: undefined };
		const trip = coastOf(FROM_EARTH, lost, 60, { arrivalMode: 'flyby' });
		expect(coastShape(trip, FROM_EARTH, lost)!.arrival).toBeNull();
		expect(trip.interstellar!.conics!.arrival).toEqual({ days: 0, km: 0 });
	});

	describe('between the two stars of a binary', () => {
		const GAP_KM = 23 * AU_KM;
		const A = starIn([0, 0, 0], 1.1);
		const B = starIn([GAP_KM, 0, 0], 0.9);

		it('keeps the two hyperbolas apart, with the line between them', () => {
			const trip = coastOf(A, B, 200, { departureMode: 'rendezvous', arrivalMode: 'rendezvous' });
			const { departure, arrival, lineFromKm, lineToKm } = coastShape(trip, A, B)!;
			expect(norm(sub(departure!.joinKm, A.starKm)) / GAP_KM).toBeCloseTo(0.25, 9);
			expect(norm(sub(arrival!.joinKm, B.starKm)) / GAP_KM).toBeCloseTo(0.25, 9);
			expect(norm(sub(lineToKm, lineFromKm)) / GAP_KM).toBeGreaterThan(0.45);
			const { conics, distanceKm } = trip.interstellar!;
			expect(conics!.departure.km + conics!.arrival.km).toBeLessThan(distanceKm);
			expect(crossingElapsed(trip, distanceKm)!.days).toBeCloseTo(trip.tofDays, 9);
		});

		it('flies planet to planet, each from its own place', () => {
			const from = planetOf(A, 1.1);
			const to = planetOf(B, 0.8);
			const trip = coastOf(from, to, 120);
			const { originKm, targetKm } = trip.interstellar!;
			expect(originKm).toEqual(endPlaceKm(from, trip.departJd));
			expect(norm(sub(targetKm, endPlaceKm(to, trip.arriveJd)))).toBeLessThan(1);
			expect(trip.inSpaceDvKms).toBeLessThanOrEqual(120);
			expect(drawnClosingKms(trip, from, to)).toBeCloseTo(rapidityOfSpeed(trip.vInfArrKms), 3);
		});

		it('leaves out a hyperbola when the orbit fills the room for it', () => {
			const from = planetOf(A, 8, { e: 0 });
			const trip = coastOf(from, B, 150, { arrivalMode: 'rendezvous' });
			const { departure, lineFromKm } = coastShape(trip, from, B)!;
			expect(departure!.seconds).toBe(0);
			expect(lineFromKm).toEqual(trip.interstellar!.originKm);
		});
	});
});

describe('the meeting with a planet', () => {
	const STAR = starIn([4.24 * LIGHT_YEAR_KM, 0, 0], 0.122);
	const SUNLIKE = starIn([4.24 * LIGHT_YEAR_KM, 0, 0]);
	const FLAT = planetOf(STAR, 0.0485, { e: 0, i: 0, om: 0, w: 0 });
	const TILTED = planetOf(STAR, 0.0485);
	const LONG = planetOf(STAR, 0.3, { e: 0.6 });
	// The line runs along x, which is the normal of this orbit.
	const ACROSS = planetOf(STAR, 0.0485, { e: 0, i: 90, om: 90, w: 0 });
	const AT_MARS: SystemEnd = {
		body: MARS,
		starKm: [0, 0, 0],
		starMu: GM_SUN_KM3_S2,
		atStar: false
	};
	const AT_EARTH: SystemEnd = { ...AT_MARS, body: EARTH };

	const STOP = { arrivalMode: 'low-orbit' } as const;
	const FLYBY = { arrivalMode: 'flyby' } as const;
	const FROM_STAR = { departureMode: 'rendezvous' } as const;

	/** A planet of `star` on a circle of 1 au. */
	const onCircle = (star: SystemEnd, extra: Partial<TravelBody['elements']>) =>
		planetOf(star, 1, { e: 0, i: 0, om: 0, w: 0, ...extra });

	/** The speed of a coast at `route`'s meeting, and of the planet there. */
	function speedsAt(route: Route, target: SystemEnd) {
		const met = elementsToState(target.body.elements, route.arriveJd)!;
		const fall = Math.sqrt(hyperbolicKms(route) ** 2 + (2 * met.mu) / norm(met.r));
		return { fall, planet: norm(met.v) };
	}

	/** The least closing speed in one period of `target`, at the speed of `route`,
	 *  and the most. */
	function closingRange(route: Route, origin: SystemEnd, target: SystemEnd) {
		const periodDays = 360 / target.body.elements.n;
		const closings = Array.from({ length: 96 }, (_, i) => {
			const arriveJd = route.arriveJd + (i * periodDays) / 96;
			return drawnClosingKms({ ...route, arriveJd }, origin, target);
		});
		return { least: Math.min(...closings), most: Math.max(...closings) };
	}

	describe.each([
		['in the plane of the line', FLAT],
		['across the line', ACROSS],
		['on a tilted orbit', TILTED]
	])('%s', (_, target) => {
		it.each([
			['flyby', FLYBY],
			['stop', STOP]
		])('draws what it prices on a %s', (_, mode) => {
			const route = coastOf(FROM_EARTH, target, 120, mode);
			expect(drawnClosingKms(route, FROM_EARTH, target)).toBeCloseTo(
				rapidityOfSpeed(route.vInfArrKms),
				3
			);
			expect(drawnExcessKms(route, FROM_EARTH, target)).toBeCloseTo(
				rapidityOfSpeed(route.vInfDepKms),
				3
			);
		});
	});

	it('meets a flat circle on a tangent hyperbola', () => {
		const route = coastOf(FROM_EARTH, FLAT, 80, STOP);
		const { fall, planet } = speedsAt(route, FLAT);
		expect(rapidityOfSpeed(route.vInfArrKms)).toBeCloseTo(fall - planet, 1);
	});

	it('pays for the crossing of an orbit that it cannot meet along its way', () => {
		const route = coastOf(FROM_EARTH, ACROSS, 80, FLYBY);
		const { fall, planet } = speedsAt(route, ACROSS);
		// The two velocities are at right angles on every phase.
		expect(rapidityOfSpeed(route.vInfArrKms)).toBeCloseTo(Math.hypot(fall, planet), 2);
		expect(rapidityOfSpeed(route.vInfArrKms)).toBeGreaterThan(1.5 * (fall - planet));
	});

	it('flies slower to a planet whose orbit lies across the line', () => {
		const flat = coastOf(FROM_EARTH, FLAT, 120, STOP);
		const across = coastOf(FROM_EARTH, ACROSS, 120, STOP);
		expect(across.interstellar!.cruiseKms).toBeLessThan(0.7 * flat.interstellar!.cruiseKms);
	});

	it('refuses a craft that can pay only for a meeting along its way', () => {
		expect(coastOf(FROM_EARTH, FLAT, 60, STOP).interstellar).toBeDefined();
		expect(coastOf(FROM_EARTH, ACROSS, 60, STOP)).toBe('cannot-stop');
	});

	it.each([
		['a tilted orbit, to stop', FROM_EARTH, TILTED, STOP],
		['a long ellipse', FROM_EARTH, LONG, STOP],
		['Mars', SUNLIKE, AT_MARS, { ...STOP, ...FROM_STAR }],
		['Earth', SUNLIKE, AT_EARTH, { ...STOP, ...FROM_STAR }]
	])('picks the phase of the least closing speed on %s', (_, origin, target, options) => {
		const route = coastOf(origin, target, 80, options);
		const { least, most } = closingRange(route, origin, target);
		const closing = drawnClosingKms(route, origin, target);
		expect(closing).toBeCloseTo(rapidityOfSpeed(route.vInfArrKms), 3);
		expect(closing).toBeLessThan(least + 0.05);
		expect(most - least).toBeGreaterThan(10);
	});

	it.each([
		['Mars', AT_MARS],
		['Earth', AT_EARTH]
	])('flies a trip from a star to %s within its budget', (_, target) => {
		const route = coastOf(SUNLIKE, target, 80, { ...STOP, ...FROM_STAR });
		expect(route.inSpaceDvKms / 80).toBeCloseTo(1, 3);
		expect(route.inSpaceDvKms).toBeLessThanOrEqual(80);
		expect(route.interstellar!.targetKm).toEqual(endPlaceKm(target, route.arriveJd));
	});

	it('searches the launch window for a planet as for a star', () => {
		const best = coastOf(FROM_EARTH, TILTED, 60, STOP);
		const periodDays = 360 / EARTH.elements.n;
		expect(best.departJd).toBeGreaterThanOrEqual(J2000);
		expect(best.departJd).toBeLessThanOrEqual(J2000 + periodDays);
		for (let i = 0; i < 24; i++) {
			const route = buildInterstellarCruiseRoute(
				FROM_EARTH,
				TILTED,
				J2000 + (i * periodDays) / 24,
				{ kind: 'budget', dvKms: 60 },
				{ departureMode: 'orbit', ...STOP }
			);
			if (typeof route === 'string' || route === null) continue;
			expect(route.interstellar!.cruiseKms).toBeLessThanOrEqual(
				best.interstellar!.cruiseKms * 1.001
			);
		}
	});

	it('does not wait for a passage that is further off than the trip is long', () => {
		const wide = planetOf(STAR, 40_000);
		const trip = coastOf(FROM_EARTH, wide, 80, STOP);
		expect(trip.inSpaceDvKms / 80).toBeCloseTo(1, 9);
		const { targetKm } = trip.interstellar!;
		expect(norm(sub(targetKm, endPlaceKm(wide, trip.arriveJd)))).toBeLessThan(1);
	});

	it('takes the short way to a planet too far out for the star to bend the path', () => {
		const wide = planetOf(STAR, 40_000);
		const trip = coastOf(FROM_EARTH, wide, 80, FLYBY);
		const shape = coastShape(trip, FROM_EARTH, wide)!;
		const { r, v } = shape.arrival!;
		expect(dot(r, v) / (norm(r) * norm(v))).toBeGreaterThan(0);
		expect((shape.seconds / SEC_PER_DAY - trip.tofDays) / trip.tofDays).toBeCloseTo(0, 6);
	});

	it('pays the real closing speed where it does not wait', () => {
		// The trip is a tenth of a period, so the next passage is further off than the
		// trip. In that time the planet turns 40° to head-on, or to the same way.
		const near = starIn([5 * AU_KM, 0, 0]);
		const budgetKms = 600;
		const headOn = onCircle(near, { ma: 45 });
		const behind = onCircle(near, { ma: 225 });
		const onTheDay = { ...STOP, launchWindow: false };
		const against = coastOf(FROM_EARTH, headOn, budgetKms, onTheDay);
		const along = coastOf(FROM_EARTH, behind, budgetKms, onTheDay);
		for (const [route, target] of [
			[against, headOn],
			[along, behind]
		] as const) {
			expect(drawnClosingKms(route, FROM_EARTH, target)).toBeCloseTo(
				rapidityOfSpeed(route.vInfArrKms),
				3
			);
			expect(drawnExcessKms(route, FROM_EARTH, target)).toBeCloseTo(
				rapidityOfSpeed(route.vInfDepKms),
				3
			);
			expect(route.inSpaceDvKms).toBeLessThanOrEqual(budgetKms);
		}
		expect(rapidityOfSpeed(against.vInfArrKms)).toBeGreaterThan(
			rapidityOfSpeed(along.vInfArrKms) + 10
		);
		expect(against.interstellar!.cruiseKms).toBeLessThan(along.interstellar!.cruiseKms);
	});

	it('refuses a stop when the real meeting costs too much', () => {
		expect(
			coastOf(FROM_EARTH, onCircle(SUNLIKE, { ma: 270 }), 40, STOP).interstellar
		).toBeDefined();
		expect(coastOf(FROM_EARTH, onCircle(SUNLIKE, { i: 90, om: 90 }), 40, STOP)).toBe('cannot-stop');
	});

	it('meets the planet where it is when no slower speed is in reach', () => {
		// For a star ahead of the body's motion the excess falls, then rises with
		// speed. Just above the floor, a launcher has only a sliver of speeds.
		const elements = { a: 1, e: 0, i: 0, om: 0, w: 0, ma: 0, epoch: J2000 };
		const n = meanMotion(GM_SUN_KM3_S2, 1);
		const from = { ...FROM_EARTH, body: { ...EARTH, elements: { ...elements, n } } };
		const ahead = starIn([AU_KM, 4.24 * LIGHT_YEAR_KM, 0], 0.122);
		// A small orbit keeps the place from moving the floor.
		const far = planetOf(ahead, 0.1, { e: 0 });
		const launch = (c3Km2S2: number) =>
			buildInterstellarCruiseRoute(
				from,
				far,
				J2000,
				{ kind: 'launch', c3Km2S2 },
				{ departureMode: 'orbit', arrivalMode: 'flyby' }
			);
		let lo = 0;
		let hi = 1e4;
		for (let i = 0; i < 80; i++) {
			const mid = (lo + hi) / 2;
			if (typeof launch(mid) === 'string') lo = mid;
			else hi = mid;
		}
		const trip = launch(hi) as Route;
		const { targetKm } = trip.interstellar!;
		expect(norm(sub(targetKm, endPlaceKm(far, trip.arriveJd)))).toBeLessThan(1);
		const closing = drawnClosingKms(trip, from, far);
		expect(closing).toBeCloseTo(rapidityOfSpeed(trip.vInfArrKms), 3);
		expect(closing).toBeGreaterThan(closingRange(trip, from, far).least + 1);
	});
});

describe('a flyby of a planet', () => {
	const STAR = starAt(4.24);
	const CIRCLE = { e: 0, i: 0, om: 0, w: 0, ma: 0 };
	const WIDE = planetOf(STAR, 400, CIRCLE);
	const NEAR = planetOf(STAR, 100, CIRCLE);
	const FLYBY = { departureMode: 'orbit', arrivalMode: 'flyby' } as const;

	it('spends the whole budget when the orbit is longer than the trip', () => {
		const wide = coastOf(FROM_EARTH, WIDE, 300, { arrivalMode: 'flyby' });
		const near = coastOf(FROM_EARTH, NEAR, 300, { arrivalMode: 'flyby' });
		expect(leg(wide, 'injection')!.dvKms).toBeCloseTo(300, 3);
		expect(wide.interstellar!.cruiseKms / near.interstellar!.cruiseKms).toBeCloseTo(1, 2);
	});

	it('gives a launcher its highest launch energy', () => {
		const drive = { kind: 'launch', c3Km2S2: 90_000 } as const;
		const route = buildInterstellarCruiseRoute(FROM_EARTH, WIDE, J2000, drive, FLYBY) as Route;
		expect(route.c3Km2S2 / drive.c3Km2S2).toBeCloseTo(1, 6);
	});
});

describe('a launch window', () => {
	const DATE_JD = 2461346.5;
	const FAR = scale([0.6, 0.7, 0.3], 4.24 * LIGHT_YEAR_KM);
	const LONG = planetOf(starIn(FAR), 400, { e: 0.05 });
	const NEARBY = planetOf(starIn([20 * AU_KM, 0, 5 * AU_KM], 0.5), 3);
	const OPTIONS = { departureMode: 'orbit', arrivalMode: 'low-orbit' } as const;
	const DRIVE = { kind: 'budget', dvKms: 300 } as const;

	it('never flies slower than a coast from the first date', () => {
		const fixed = buildInterstellarCruiseRoute(LONG, NEARBY, DATE_JD, DRIVE, OPTIONS) as Route;
		const found = buildInterstellarCruiseRoute(LONG, NEARBY, DATE_JD, DRIVE, {
			...OPTIONS,
			launchWindow: true
		}) as Route;
		expect(found.interstellar!.cruiseKms).toBeGreaterThanOrEqual(fixed.interstellar!.cruiseKms);
		expect(
			fastestCrossingEndJd(LONG, NEARBY, DATE_JD, DRIVE, { ...OPTIONS, launchWindow: true })
		).toBe(routeEndJd(found));
	});
});

describe('an orbit at a star', () => {
	const STAR = starAt(4.24);
	const SUN: SystemEnd = { ...starAt(0), body: { ...starAt(0).body, id: 'naif-10' } };
	const CIRCLE: EndOrbit = { rPeriKm: AU_KM, rApoKm: AU_KM };
	/** Speed of escape less circular speed at 1 au of one solar mass, km/s. */
	const HELD = (Math.SQRT2 - 1) * Math.sqrt(GM_SUN_KM3_S2 / AU_KM);

	it('costs 12.3 km/s in and out of a circle at 1 au under a held drive', () => {
		const arriving = buildInterstellarTorchRoute(FROM_EARTH, STAR, J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			targetOrbit: CIRCLE
		})!;
		expect(leg(arriving, 'capture')!.dvKms).toBeCloseTo(HELD, 6);
		expect(arriving.targetOrbit).toEqual(CIRCLE);
		expect(HELD).toBeCloseTo(12.3, 1);
		const leaving = buildInterstellarTorchRoute(STAR, SUN, J2000, G0_M_S2, {
			departureMode: 'orbit',
			departureOrbit: CIRCLE,
			arrivalMode: 'rendezvous'
		})!;
		expect(leg(leaving, 'injection')!.dvKms).toBeCloseTo(HELD, 6);
	});

	it('prices a coast into an orbit with the ordinary arrival cost', () => {
		const trip = coastOf(FROM_EARTH, STAR, 60, { targetOrbit: CIRCLE });
		const figure = hyperbolicKms(trip);
		expect(leg(trip, 'capture')!.dvKms).toBeCloseTo(
			arrivalCost(STAR.body, figure, 'low-orbit', 'none', CIRCLE).captureKms,
			9
		);
		// The circle costs 12.3 km/s more than the hold, at any one speed.
		expect(
			leg(trip, 'capture')!.dvKms - captureDv(GM_SUN_KM3_S2, AU_KM, Infinity, figure)
		).toBeCloseTo(HELD, 6);
		expect(trip.inSpaceDvKms / 60).toBeCloseTo(1, 9);
	});

	it('prices a coast out of an orbit with the ordinary departure cost', () => {
		const trip = coastOf(STAR, SUN, 60, {
			departureOrbit: CIRCLE,
			arrivalMode: 'rendezvous'
		});
		const figure = hyperbolicKms(trip);
		expect(leg(trip, 'injection')!.dvKms).toBeCloseTo(
			departureCost(STAR.body, figure, 'orbit', CIRCLE).injectionKms,
			9
		);
		expect(rapidityOfSpeed(trip.vInfDepKms)).toBeCloseTo(figure, 6);
	});

	it('keeps the hold for a rendezvous, in both roles', () => {
		const trip = coastOf(STAR, SUN, 30, {
			departureMode: 'rendezvous',
			arrivalMode: 'rendezvous',
			departureOrbit: CIRCLE,
			targetOrbit: CIRCLE
		});
		const figure = hyperbolicKms(trip);
		const pass = captureDv(GM_SUN_KM3_S2, AU_KM, Infinity, figure);
		expect(leg(trip, 'injection')!.dvKms).toBeCloseTo(pass, 6);
		expect(leg(trip, 'rendezvous')!.dvKms).toBeCloseTo(pass, 6);
	});

	it('brings a hyperbola down to the periapsis of a wide orbit', () => {
		const wide = { rPeriKm: 400 * AU_KM, rApoKm: 1000 * AU_KM };
		const trip = coastOf(FROM_EARTH, STAR, 60, { arrivalMode: 'capture', targetOrbit: wide });
		const conic = coastShape(trip, FROM_EARTH, STAR)!.arrival!;
		expect(norm(conic.r) / AU_KM).toBeCloseTo(400, 6);
		expect(norm(sub(conic.joinKm, conic.starKm)) / AU_KM).toBeCloseTo(1000, 3);
	});

	it('never prices an orbit at a star of unknown mass', () => {
		const unknown: SystemEnd = {
			...STAR,
			starMu: undefined,
			body: { ...STAR.body, mu: 0 }
		};
		const options = { departureMode: 'orbit', targetOrbit: CIRCLE } as const;
		const hold = coastOf(FROM_EARTH, unknown, 60, { arrivalMode: 'rendezvous' });
		const trip = coastOf(FROM_EARTH, unknown, 60, { ...options, arrivalMode: 'low-orbit' });
		expect(trip.targetOrbit).toBeUndefined();
		expect(trip.interstellar!.cruiseKms).toBeCloseTo(hold.interstellar!.cruiseKms, 9);
		const held = buildInterstellarTorchRoute(FROM_EARTH, unknown, J2000, G0_M_S2, {
			...options,
			arrivalMode: 'low-orbit'
		})!;
		expect(held.targetOrbit).toBeUndefined();
		expect(leg(held, 'capture')).toBeUndefined();
	});
});

describe('no speed above c', () => {
	const BUDGET_KMS = 1e8;
	const STAR = starAt(4.24);
	const speedsOf = (route: Route) => [
		route.vInfDepKms,
		route.vInfArrKms,
		route.interstellar!.cruiseKms,
		...(route.peakSpeedKms === undefined ? [] : [route.peakSpeedKms]),
		...(route.entrySpeedKms === undefined ? [] : [route.entrySpeedKms])
	];
	const TARGETS: [string, SystemEnd, SystemEnd][] = [
		['a star', FROM_EARTH, STAR],
		['a planet', FROM_EARTH, PROXIMA_B],
		['a solar moon', STAR, moonOf(MOON, EARTH)]
	];
	const flyby = { arrivalMode: 'flyby' } as const;
	const leaveFrom = (origin: SystemEnd) =>
		origin.atStar ? ({ departureMode: 'rendezvous' } as const) : {};

	it.each(TARGETS)('holds on a coast past %s, at any budget', (_, origin, target) => {
		const route = coastOf(origin, target, BUDGET_KMS, { ...flyby, ...leaveFrom(origin) });
		for (const speed of speedsOf(route)) expect(speed).toBeLessThan(C);
		// A Δv spend is a figure, and it can pass c.
		expect(route.inSpaceDvKms).toBeGreaterThan(C);
	});

	it.each(TARGETS)('holds on a held drive past %s, at any push', (_, origin, target) => {
		const route = buildInterstellarTorchRoute(origin, target, J2000, 1e13, {
			departureMode: 'orbit',
			...flyby,
			...leaveFrom(origin)
		})!;
		for (const speed of speedsOf(route)) expect(speed).toBeLessThan(C);
		expect(leg(route, 'boost')!.dvKms).toBeGreaterThan(C);
	});

	it('holds from a moon, through the wells it climbs', () => {
		const from = moonOf(MOON, EARTH);
		const route = coastOf(from, STAR, BUDGET_KMS, flyby);
		for (const speed of speedsOf(route)) expect(speed).toBeLessThan(C);
	});

	it.each([
		['the Moon', MOON, EARTH],
		['Europa', EUROPA, JUPITER]
	])('holds on a stop at %s, through the wells it falls down', (_, moon, planet) => {
		const route = coastOf(STAR, moonOf(moon, planet), BUDGET_KMS, {
			departureMode: 'rendezvous'
		});
		for (const speed of speedsOf(route)) expect(speed).toBeLessThan(C);
		expect(route.interstellar!.rapidityKms).toBeGreaterThan(C);
	});

	it('holds at the entry into an atmosphere', () => {
		const air = { ...EARTH, aeroPressurePa: 101_325, aeroScaleHeightKm: 8.5 };
		const home = { ...FROM_EARTH, body: air };
		const route = coastOf(STAR, home, BUDGET_KMS, {
			departureMode: 'rendezvous',
			arrivalMode: 'landing',
			aero: 'aerobraking'
		});
		expect(route.entrySpeedKms).toBeGreaterThan(0);
		for (const speed of speedsOf(route)) expect(speed).toBeLessThan(C);
	});

	it('keeps the launch energy a costed figure', () => {
		const route = coastOf(FROM_EARTH, STAR, 4e5, flyby);
		expect(route.vInfDepKms).toBeLessThan(C);
		expect(route.c3Km2S2).toBeGreaterThan(C ** 2);
		expect(route.c3Km2S2).toBeCloseTo(rapidityOfSpeed(route.vInfDepKms) ** 2, 0);
	});

	it('reads a speed back to its figure', () => {
		for (const figure of [10, 30_000, 400_000, 2e6]) {
			expect(rapidityOfSpeed(speedOfRapidity(figure)) / figure).toBeCloseTo(1, 6);
		}
		expect(speedOfRapidity(40)).toBeCloseTo(40, 6);
		expect(speedOfRapidity(1e12)).toBeLessThan(C);
	});

	it('keeps the sweep of the matter finite at the top speed', () => {
		const route = coastOf(FROM_EARTH, STAR, BUDGET_KMS, flyby);
		const phi = route.interstellar!.rapidityKms / C;
		expect(crossingSweep(route)!.peakExcess / Math.cosh(phi)).toBeCloseTo(1, 6);
		const SHIP_TIME: RapidityRate = { at: () => 1, fromRest: (x) => x };
		const seconds = (route.tofDays * SEC_PER_DAY) / route.interstellar!.gamma;
		expect(crossingIntegral(route, SHIP_TIME)! / seconds).toBeCloseTo(1, 6);
	});
});

describe('crossingSweep', () => {
	it('weighs a coast by γ − 1 at its one speed', () => {
		const route = buildInterstellarCruiseRoute(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			{ kind: 'budget', dvKms: 40 },
			{ departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true }
		) as Route;
		const sweep = crossingSweep(route)!;
		const crossing = route.interstellar!;
		const { gamma } = crossing;
		expect(sweep.peakExcess / (gamma - 1)).toBeCloseTo(1, 6);
		expect(sweep.excessKm / ((gamma - 1) * crossingFlownKm(crossing))).toBeCloseTo(1, 6);
		expect(sweep.peakAtKm).toBe(0);
	});

	it('takes half the peak on a flat-out burn, which climbs from rest', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		})!;
		const sweep = crossingSweep(route)!;
		const { gamma, distanceKm } = route.interstellar!;
		expect(sweep.peakExcess).toBeCloseTo(gamma - 1, 9);
		expect(sweep.excessKm / (((gamma - 1) * distanceKm) / 2)).toBeCloseTo(1, 9);
		expect(sweep.peakAtKm / distanceKm).toBeCloseTo(0.5, 9);
	});

	it('reaches the peak at the target on a flyby', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'flyby'
		})!;
		expect(crossingSweep(route)!.peakAtKm).toBeCloseTo(route.interstellar!.distanceKm, 0);
	});

	it('says nothing about a route inside the solar system', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2)!;
		expect(crossingSweep({ ...route, interstellar: undefined })).toBeNull();
	});
});

describe('interstellarDrive', () => {
	const craft = (fields: Partial<Vehicle>): Vehicle =>
		({ id: 'c', kind: 'probe', propulsion: 'chemical', status: 'active', ...fields }) as Vehicle;

	it('asks for a craft before anything else', () => {
		expect(interstellarDrive(null, 0)).toBe('no-craft');
	});

	it('flies a held drive only where the propellant is no limit', () => {
		expect(interstellarDrive(craft({ unlimitedDv: true, accelMs2: { value: 9.8 } }), 0)).toEqual({
			kind: 'torch',
			accelMs2: 9.8
		});
		// A ship with no limit and no acceleration has nothing to fly between stars.
		expect(interstellarDrive(craft({ unlimitedDv: true }), 0)).toBe('no-drive');
		expect(interstellarDrive(craft({ accelMs2: { value: 0.0002 } }), 0)).toBe('no-drive');
	});

	it('takes the Δv with the payload aboard', () => {
		const stage = craft({
			dvKms: 8,
			dryMassKg: { value: 1000 },
			propellantMassKg: { value: 3000 },
			ispS: { value: 450 },
			thrustN: { value: 50_000 }
		});
		const drive = interstellarDrive(stage, 1000);
		expect(drive).toMatchObject({ kind: 'budget' });
		expect((drive as { dvKms: number }).dvKms).toBeLessThan(8);
	});

	it('refuses a drive too weak to burn', () => {
		const ion = craft({
			propulsion: 'electric',
			dvKms: 10,
			dryMassKg: { value: 1000 },
			propellantMassKg: { value: 400 },
			thrustN: { value: 0.09 }
		});
		expect(interstellarDrive(ion, 0)).toBe('low-thrust');
	});

	it('reads a launcher off its curve at the payload', () => {
		const launcher = craft({
			kind: 'launcher',
			c3Curve: {
				points: [
					[0, 10_000],
					[100, 2_000],
					[160, 500]
				],
				source: 'test',
				truncated: false
			}
		});
		expect(interstellarDrive(launcher, 0)).toEqual({ kind: 'launch', c3Km2S2: 160 });
		expect(interstellarDrive(launcher, 1_000)).toEqual({ kind: 'launch', c3Km2S2: 140 });
		expect(interstellarDrive(craft({ kind: 'launcher' }), 0)).toBe('no-drive');
	});
});

describe('fastestCrossingEndJd', () => {
	const options = { departureMode: 'orbit', arrivalMode: 'rendezvous' } as const;

	it('ends with the flat-out arc of a held drive, before every coast of it', () => {
		const endJd = fastestCrossingEndJd(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			{ kind: 'torch', accelMs2: G0_M_S2 },
			options
		)!;
		const flatOut = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, options)!;
		expect(endJd).toBe(routeEndJd(flatOut));
		const coasting = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			...options,
			coastFraction: 0.1
		})!;
		expect(endJd).toBeLessThan(routeEndJd(coasting));
	});

	it('ends with the coast of a Δv budget that leaves on that date', () => {
		const drive = { kind: 'budget', dvKms: 40 } as const;
		const coast = buildInterstellarCruiseRoute(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			drive,
			options
		) as Route;
		expect(fastestCrossingEndJd(FROM_EARTH, starAt(4.24), J2000, drive, options)).toBe(
			routeEndJd(coast)
		);
	});

	it('gives nothing when the craft has no route', () => {
		const drive = { kind: 'budget', dvKms: 5 } as const;
		expect(fastestCrossingEndJd(FROM_EARTH, starAt(4.24), J2000, drive, options)).toBeNull();
	});
});

describe('crossingElapsed', () => {
	it('runs from nothing at departure to the whole crossing at arrival', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous',
			coastFraction: 0.25
		})!;
		const distanceKm = route.interstellar!.distanceKm;
		expect(crossingElapsed(route, 0)).toEqual({ days: 0, shipDays: 0 });
		const end = crossingElapsed(route, distanceKm)!;
		expect(end.days).toBeCloseTo(route.tofDays, 6);
		expect(end.shipDays).toBeCloseTo(routeShipDays(route), 6);
		// A symmetric arc is half done at half the distance.
		const half = crossingElapsed(route, distanceKm / 2)!;
		expect(half.days).toBeCloseTo(route.tofDays / 2, 6);
		let last = -1;
		for (let i = 0; i <= 20; i++) {
			const at = crossingElapsed(route, (distanceKm * i) / 20)!;
			expect(at.days).toBeGreaterThan(last);
			last = at.days;
		}
	});

	it('reads a coast through its two wells and along its line', () => {
		const route = buildInterstellarCruiseRoute(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			{ kind: 'budget', dvKms: 40 },
			{ departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true }
		) as Route;
		const { distanceKm, conics, cruiseKms } = route.interstellar!;
		const { departure, arrival } = conics!;
		expect(crossingElapsed(route, 0)!.days).toBe(0);
		expect(crossingElapsed(route, distanceKm)!.days).toBeCloseTo(route.tofDays, 6);
		expect(crossingElapsed(route, departure.km)!.days).toBeCloseTo(departure.days, 6);
		const end = crossingElapsed(route, distanceKm - arrival.km)!.days;
		expect(end).toBeCloseTo(route.tofDays - arrival.days, 6);
		// The line is flown at the cruise speed.
		const lineKm = distanceKm - departure.km - arrival.km;
		const lineDays = end - departure.days;
		expect(lineKm / lineDays / SEC_PER_DAY / cruiseKms).toBeCloseTo(1, 6);
	});

	describe('from a ring wider than the gap between the ends', () => {
		const NEARBY = starIn([20 * AU_KM, 0, 5 * AU_KM], 0.5);
		const SUN = starAt(0);
		const RING: EndOrbit = { rPeriKm: 900 * AU_KM, rApoKm: 900 * AU_KM };
		const ONE_PER_SECOND: RapidityRate = { at: () => 1, fromRest: (phi) => phi };

		it.each([
			['leaving', SUN, NEARBY, { departureOrbit: RING, arrivalMode: 'rendezvous' }],
			['reaching', NEARBY, SUN, { departureMode: 'rendezvous', targetOrbit: RING }]
		] as const)('spreads the whole trip over the crossing, %s it', (_, origin, target, options) => {
			const route = coastOf(origin, target, 3000, { ...options, launchWindow: false });
			const { distanceKm, gamma } = route.interstellar!;
			const elapsed = (km: number) => crossingElapsed(route, km)!.days;
			expect(elapsed(distanceKm) / route.tofDays).toBeCloseTo(1, 9);
			expect(elapsed(distanceKm / 2) / route.tofDays).toBeCloseTo(0.5, 9);
			expect(crossingIntegral(route, ONE_PER_SECOND)! / SEC_PER_DAY).toBeCloseTo(
				route.tofDays / gamma,
				6
			);
		});

		it('flies the width of the ring, which is many times the gap', () => {
			const options = { departureOrbit: RING, arrivalMode: 'rendezvous' } as const;
			const route = coastOf(SUN, NEARBY, 3000, { ...options, launchWindow: false });
			const crossing = route.interstellar!;
			const flownKm = crossingFlownKm(crossing);
			expect(flownKm / crossing.distanceKm).toBeGreaterThan(40);
			expect(flownKm / (crossing.cruiseKms * route.tofDays * SEC_PER_DAY)).toBeCloseTo(1, 3);
			const { peakExcess, excessKm } = crossingSweep(route)!;
			expect(excessKm / (peakExcess * flownKm)).toBeCloseTo(1, 9);
		});
	});

	it('says nothing about a route inside the solar system', () => {
		const route = buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2)!;
		expect(crossingElapsed({ ...route, interstellar: undefined }, 1)).toBeNull();
	});
});

describe('crossingIntegral', () => {
	/** One per ship second. Its total is the ship time, s. */
	const SHIP_TIME: RapidityRate = { at: () => 1, fromRest: (phi) => phi };
	/** The proper speed γβc. Its total is the distance, km. */
	const DISTANCE: RapidityRate = {
		at: (phi) => C * Math.sinh(phi),
		fromRest: (phi) => 2 * C * Math.sinh(phi / 2) ** 2
	};
	const torch = (arrivalMode: ArrivalMode, coastFraction: number) =>
		buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode,
			coastFraction
		})!;
	const coast = (dvKms: number) =>
		buildInterstellarCruiseRoute(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			{ kind: 'budget', dvKms },
			{ departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true }
		) as Route;
	const routes = [
		torch('rendezvous', 0),
		torch('rendezvous', 0.4),
		torch('flyby', 0),
		torch('flyby', 0.4),
		coast(40),
		coast(400_000)
	];

	it('gives the ship time of crossingElapsed between any two points', () => {
		for (const route of routes) {
			const totalKm = route.interstellar!.distanceKm;
			for (const [from, to] of [
				[0, 1],
				[0, 0.3],
				[0.2, 0.7],
				[0.45, 0.55],
				[0.6, 1]
			]) {
				const seconds = crossingIntegral(route, SHIP_TIME, from * totalKm, to * totalKm)!;
				const elapsed =
					crossingElapsed(route, to * totalKm)!.shipDays -
					crossingElapsed(route, from * totalKm)!.shipDays;
				expect(seconds / SEC_PER_DAY / elapsed).toBeCloseTo(1, 9);
			}
		}
	});

	it('gives the distance for the proper speed, and adds up over the parts', () => {
		for (const route of routes) {
			const totalKm = route.interstellar!.distanceKm;
			// A coast outruns its cruise speed in the wells, by a little.
			const digits = route.interstellar!.conics ? 4 : 9;
			expect(crossingIntegral(route, DISTANCE)! / totalKm).toBeCloseTo(1, digits);
			for (const at of [0.1, 0.5, 0.9]) {
				const split =
					crossingIntegral(route, SHIP_TIME, 0, at * totalKm)! +
					crossingIntegral(route, SHIP_TIME, at * totalKm)!;
				expect(split / crossingIntegral(route, SHIP_TIME)!).toBeCloseTo(1, 12);
			}
		}
	});

	it('gives nothing for an empty stretch, and clamps to the crossing', () => {
		const route = routes[1];
		const totalKm = route.interstellar!.distanceKm;
		expect(crossingIntegral(route, SHIP_TIME, totalKm / 3, totalKm / 3)).toBe(0);
		expect(crossingIntegral(route, SHIP_TIME, -totalKm, 2 * totalKm)).toBe(
			crossingIntegral(route, SHIP_TIME)
		);
	});

	it('says nothing about a route inside the solar system', () => {
		expect(crossingIntegral({ ...routes[0], interstellar: undefined }, SHIP_TIME)).toBeNull();
	});
});

describe('crossingStretches', () => {
	const torch = (coastFraction: number, arrivalMode: 'rendezvous' | 'flyby') =>
		buildInterstellarTorchRoute(FROM_EARTH, starAt(4.24), J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode,
			coastFraction
		})!;

	it('follows the legs of the crossing, end to end along the line', () => {
		for (const [route, kinds] of [
			[torch(0, 'rendezvous'), ['boost', 'brake']],
			[torch(0.25, 'rendezvous'), ['boost', 'cruise', 'brake']],
			[torch(0, 'flyby'), ['boost']],
			[torch(0.25, 'flyby'), ['boost', 'cruise']]
		] as const) {
			const stretches = crossingStretches(route)!;
			expect(stretches.map((s) => s.kind)).toEqual(kinds);
			expect(stretches[0].fromKm).toBe(0);
			expect(stretches.at(-1)!.toKm).toBe(route.interstellar!.distanceKm);
			for (let i = 1; i < stretches.length; i++) {
				expect(stretches[i].fromKm).toBe(stretches[i - 1].toKm);
			}
			// Each stretch ends where the kernel says its leg ends.
			let days = 0;
			for (const stretch of stretches) {
				days += route.legs.find((l) => l.kind === stretch.kind)!.days;
				expect(crossingElapsed(route, stretch.toKm)!.days / days).toBeCloseTo(1, 9);
			}
		}
	});

	it('is one cruise on a coast, and nothing on a route in one system', () => {
		const coast = buildInterstellarCruiseRoute(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			{ kind: 'budget', dvKms: 41 },
			{ departureMode: 'orbit', arrivalMode: 'flyby' }
		) as Route;
		expect(crossingStretches(coast)).toEqual([
			{ kind: 'cruise', fromKm: 0, toKm: coast.interstellar!.distanceKm }
		]);
		expect(crossingStretches({ ...coast, interstellar: undefined })).toBeNull();
	});
});
