import { describe, it, expect } from 'vitest';
import { DAYS_PER_YEAR } from '$lib/time/jd';
import { AU_KM, LIGHT_YEAR_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { G0_M_S2, GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import {
	buildInterstellarCruiseRoute,
	buildInterstellarTorchRoute,
	crossingElapsed,
	crossingIntegral,
	crossingStretches,
	crossingSweep,
	fastestCrossingEndJd,
	interstellarDrive,
	type InterstellarCruiseOptions,
	type InterstellarDrive,
	type RapidityRate,
	type SystemEnd
} from './interstellar';
import type { TravelBody } from './body';
import { arrivalCost, captureDv, departureCost, type ArrivalMode } from './maneuvers';
import { routeEndJd, routeShipDays, type Route } from './route';
import { elementsToState } from './state';
import { EARTH, EUROPA, J2000, JUPITER, MOON } from './test-fixtures';
import { normalize, scale, type Vec3 } from './vec3';
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

/** The classical cruise speed that the hyperbolas of a coast use, km/s. The
 *  route keeps the true speed, c·tanh of this over c. */
function hyperbolicKms(route: Route): number {
	return C * Math.atanh(route.interstellar!.cruiseKms / C);
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
		const distanceKm = 1e9;
		const near = { ...starAt(0), starKm: [distanceKm, 0, 0] as [number, number, number] };
		const route = buildInterstellarTorchRoute(starAt(0), near, J2000, accelMs2, {
			departureMode: 'rendezvous',
			arrivalMode: 'rendezvous'
		})!;
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
		const phi = Math.acosh(1 + ((G0_M_S2 / 1000) * 4.24 * LIGHT_YEAR_KM) / C ** 2);
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

	/** A star 4.24 ly out along the unit vector `direction`. */
	function starToward(direction: Vec3): SystemEnd {
		const end = starAt(4.24);
		return { ...end, starKm: scale(direction, 4.24 * LIGHT_YEAR_KM) };
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
		const out = normalize(elementsToState(FROM_CIRCLE.body.elements, J2000, MU)!.r);
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

	it('moves a planet with no period at the mean motion of its star', () => {
		const still = {
			...FROM_CIRCLE,
			body: { ...FROM_CIRCLE.body, elements: { ...FROM_CIRCLE.body.elements, n: 0 } }
		};
		const drive = { kind: 'budget', dvKms: 30 } as const;
		const options = { departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true } as const;
		const target = starToward([0, 1, 0]);
		expect(coast(still, target, drive, options).interstellar!.cruiseKms).toBeCloseTo(
			coast(FROM_CIRCLE, target, drive, options).interstellar!.cruiseKms,
			9
		);
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
		expect(route.vInfArrKms).toBeCloseTo(cruise, 9);
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
		expect(route.vInfDepKms).toBeCloseTo(hyperbolicKms(route), 9);
	});

	it('meets a planet at the periastron of its orbit', () => {
		const eccentric: SystemEnd = {
			...PROXIMA_B,
			body: { ...PROXIMA_B.body, elements: { ...PROXIMA_B.body.elements, e: 0.3 } }
		};
		const route = coast(
			FROM_CIRCLE,
			{ ...eccentric, starKm: [4.24 * LIGHT_YEAR_KM, 0, 0] },
			{ kind: 'budget', dvKms: 60 },
			{ departureMode: 'orbit', arrivalMode: 'low-orbit', launchWindow: true }
		);
		expect(route.legs.map((l) => l.kind)).toEqual(['injection', 'cruise', 'capture']);
		// It meets the planet at the periastron at the difference of the two speeds.
		const mu = PROXIMA_B.starMu!;
		const q = 0.0485 * 0.7 * AU_KM;
		const fall = Math.sqrt(hyperbolicKms(route) ** 2 + (2 * mu) / q);
		expect(route.vInfArrKms).toBeCloseTo(fall - Math.sqrt((mu * 1.3) / q), 6);
		expect(leg(route, 'capture')!.dvKms).toBeCloseTo(
			arrivalCost(PROXIMA_B.body, route.vInfArrKms, 'low-orbit').captureKms,
			9
		);
	});

	it('meets a planet with an assumed orbit on the circle at its semi-major axis', () => {
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
		const r = 0.0485 * AU_KM;
		const fall = Math.sqrt(hyperbolicKms(route) ** 2 + (2 * mu) / r);
		expect(route.vInfArrKms).toBeCloseTo(fall - Math.sqrt(mu / r), 6);
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
		expect(route.tofDays * SEC_PER_DAY).toBeGreaterThan(distanceKm / C);
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
		for (let i = 0; i <= 22; i++) {
			const dvKms = 23.9 + i * 0.1;
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
					expect(route.inSpaceDvKms / dvKms).toBeCloseTo(1, 9);
					const fit = checkFeasibility(craft({ dvKms }), route);
					if (fit.status !== 'ok')
						failed.push(`${dvKms.toFixed(1)} ${arrivalMode}: ${fit.marginKms}`);
				}
			}
		}
		expect(routes).toBeGreaterThan(100);
		expect(failed).toEqual([]);
	});

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
				expect(route.c3Km2S2 / topC3).toBeCloseTo(1, 9);
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
		expect(route.vInfDepKms).toBeCloseTo(inside(moon, planet, v), 6);
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
		const route = coast(
			STAR,
			moonEnd(moon, planet),
			{ kind: 'budget', dvKms: 80 },
			{ departureMode: 'rendezvous', arrivalMode: 'low-orbit' }
		);
		const { a, e } = planet.elements;
		const q = a * (1 - e) * AU_KM;
		const fall = Math.sqrt(hyperbolicKms(route) ** 2 + (2 * MU) / q);
		const atPlanet = fall - Math.sqrt((MU * (1 + e)) / q);
		expect(route.vInfArrKms).toBeCloseTo(inside(moon, planet, atPlanet), 6);
		expect(leg(route, 'capture')!.dvKms).toBeCloseTo(
			arrivalCost(moon, route.vInfArrKms, 'low-orbit').captureKms,
			9
		);
	});

	it("climbs out of the planet's well and falls into it under a held drive", () => {
		const out = buildInterstellarTorchRoute(moonEnd(MOON, EARTH), STAR, J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		})!;
		const escapeKms = inside(MOON, EARTH, 0);
		expect(out.vInfDepKms).toBeCloseTo(escapeKms, 9);
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
		const { gamma, distanceKm } = route.interstellar!;
		expect(sweep.peakExcess / (gamma - 1)).toBeCloseTo(1, 6);
		expect(sweep.excessKm / ((gamma - 1) * distanceKm)).toBeCloseTo(1, 6);
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

	it('reads a coast at its one speed', () => {
		const route = buildInterstellarCruiseRoute(
			FROM_EARTH,
			starAt(4.24),
			J2000,
			{ kind: 'budget', dvKms: 40 },
			{ departureMode: 'orbit', arrivalMode: 'flyby', launchWindow: true }
		) as Route;
		expect(crossingElapsed(route, route.interstellar!.distanceKm)!.days).toBeCloseTo(
			route.tofDays,
			6
		);
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
			expect(crossingIntegral(route, DISTANCE)! / totalKm).toBeCloseTo(1, 9);
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
