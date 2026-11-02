/**
 * A trip between two moons of one planet, end to end: search bounds, grid,
 * offered routes.
 *
 * Not special geometry — both ends orbit Jupiter the way Earth and Mars orbit
 * the Sun, so it is the same Lambert solve with a different mass at the focus.
 * What it does break is every bound stated in bare days: Io to Europa is a
 * 1.3-day crossing with a 3.5-day synodic period, so a 60-day floor grids
 * seventeen windows at once and a 15-day cruise floor asks for arcs that are
 * ten transfers long.
 */

import { describe, it, expect } from 'vitest';
import {
	buildConstantThrustRoute,
	buildLowThrustRoute,
	buildRoute,
	buildTrajectoryPath,
	computePorkchop,
	elementsToState,
	GM_SUN_KM3_S2,
	hohmannTransferDays,
	norm,
	selectRoutes,
	sub,
	type EndOrbit,
	type RouteOptions,
	type TravelBody
} from '$lib/math/travel';
import { EUROPA, IO, JUPITER, MARS, EARTH } from '$lib/math/travel/test-fixtures';
import { AU_KM, SOLAR_RADIUS_KM } from '$lib/math/units';
import { OrbitalSource } from '$lib/fetch/position/format';
import { ObjectType, type BodyData } from '$lib/types/objects';
import { extrasolarTravelBody, type ExtrasolarEnd } from './extrasolar-end';
import { routeHazards } from './hazards';
import { orbitChoices, type OrbitFacts } from './orbits';
import { searchWindow, type WindowRequest } from './search-window';
import { lookupIn, transferCenterId, transferFrame, transferPlan } from './travel-body';

/** Inside the fixtures' epoch, so the moons are where the elements say. */
const NOW = 2461240.5;

const JOVIAN = { origin: IO, target: EUROPA, nowJd: NOW, centralMu: JUPITER.mu } as const;

const hohmann = hohmannTransferDays(IO, EUROPA, JUPITER.mu)!;

describe('search bounds about a planet', () => {
	it('takes the crossing time from the planet mass, not the Sun', () => {
		// About 1.3 days. Priced against the Sun instead it would be ~11 years.
		expect(hohmann).toBeGreaterThan(1);
		expect(hohmann).toBeLessThan(2);
	});

	it('brackets that crossing with the cruise bounds', () => {
		const options = searchWindow({ ...JOVIAN, timeMode: 'now' })!;
		expect(options.tofMinDays).toBeLessThan(hohmann);
		expect(options.tofMaxDays).toBeGreaterThan(hohmann);
	});

	it('spans one synodic period, not the two-month floor a planet would get', () => {
		const options = searchWindow({ ...JOVIAN, timeMode: 'now' })!;
		const span = options.departToJd - options.departFromJd;
		// Io laps Europa every 3.5 days.
		expect(span).toBeGreaterThan(3);
		expect(span).toBeLessThan(4);
	});

	it('carries the planet mass through to the solver', () => {
		expect(searchWindow({ ...JOVIAN, timeMode: 'now' })!.centralMu).toBe(JUPITER.mu);
	});

	it('keeps the slack around a chosen date inside the span', () => {
		const picked = NOW + 2;
		const options = searchWindow({ ...JOVIAN, timeMode: 'depart', pickedJd: picked })!;
		expect(options.departToJd - options.departFromJd).toBeLessThan(4);
		expect(options.departToJd).toBeGreaterThan(picked);
	});

	// The floors capping a short crossing must not move a trip that really is
	// months long.
	it('leaves an interplanetary window where it was', () => {
		const options = searchWindow({ origin: EARTH, target: MARS, nowJd: NOW, timeMode: 'now' })!;
		expect(options.tofMinDays).toBeGreaterThan(80);
		expect(options.departToJd - options.departFromJd).toBeGreaterThan(700);
	});
});

describe('routes between two moons', () => {
	const options = searchWindow({ ...JOVIAN, timeMode: 'now' })!;
	const solveOptions = {
		...options,
		departureMode: 'orbit' as const,
		arrivalMode: 'low-orbit' as const
	};
	const grid = computePorkchop(IO, EUROPA, solveOptions);

	it('solves most of the grid', () => {
		expect(grid.solvedCount).toBeGreaterThan(grid.departSteps * grid.tofSteps * 0.5);
	});

	it('offers routes at all', () => {
		expect(selectRoutes(grid, IO, EUROPA, solveOptions).length).toBeGreaterThan(0);
	});

	// Io is doing 17.3 km/s about Jupiter and Europa 13.7, so the transfer costs
	// about 1.9 km/s to leave and 1.7 to arrive, and Oberth takes most of both
	// back at the moons themselves. A few km/s in space, not tens.
	it('prices the cheapest one the way a Galilean tour is priced', () => {
		const routes = selectRoutes(grid, IO, EUROPA, solveOptions);
		const cheapest = Math.min(...routes.map((r) => r.route.inSpaceDvKms));
		expect(cheapest).toBeGreaterThan(1);
		expect(cheapest).toBeLessThan(5);
	});

	it('gets there in days', () => {
		const routes = selectRoutes(grid, IO, EUROPA, solveOptions);
		for (const { route } of routes) expect(route.tofDays).toBeLessThan(5);
	});

	it('works the same way inbound', () => {
		const back = searchWindow({
			origin: EUROPA,
			target: IO,
			nowJd: NOW,
			centralMu: JUPITER.mu,
			timeMode: 'now'
		})!;
		const inbound = { ...back, departureMode: 'orbit' as const, arrivalMode: 'low-orbit' as const };
		const routes = selectRoutes(computePorkchop(EUROPA, IO, inbound), EUROPA, IO, inbound);
		expect(routes.length).toBeGreaterThan(0);
		expect(Math.min(...routes.map((r) => r.route.inSpaceDvKms))).toBeLessThan(5);
	});
});

/**
 * TRAPPIST-1 as the export gives it. Nothing here orbits the Sun, and the star has
 * no row in any solar lookup.
 */
describe('a trip inside the system of another star', () => {
	const STAR_ID = 'x-558442032';
	const NOW_ = 2461240.5;
	const STAR_MU = 0.0898 * GM_SUN_KM3_S2;
	const STAR_RADIUS_KM = 0.1192 * SOLAR_RADIUS_KM;
	const NO_LOOKUP = lookupIn(new Map());
	const DAWN = { accelMs2: 0.092 / 1218, veKms: 30.4 };
	const G = 9.80665;

	function row(id: string, over: Partial<BodyData>): BodyData {
		return {
			id,
			name: id,
			hasLocalized: false,
			objectType: ObjectType.EXOPLANET,
			parentId: STAR_ID,
			radiusKm: NaN,
			a: 0,
			e: 0,
			i: 0,
			om: 0,
			w: 0,
			ma: 0,
			n: 0,
			epoch: 2457000,
			validityStart: -Infinity,
			validityEnd: Infinity,
			orbitalSource: OrbitalSource.UNKNOWN,
			...over
		};
	}

	const STAR = (muKm3S2: number | null): ExtrasolarEnd['star'] => ({
		id: STAR_ID,
		positionKm: [3.6e14, -8.6e13, -3.3e13],
		orbits: [],
		fixedId: STAR_ID,
		muKm3S2,
		radiusKm: STAR_RADIUS_KM,
		class: 'star'
	});

	function starEnd(muKm3S2: number | null = STAR_MU): ExtrasolarEnd {
		return {
			body: row(STAR_ID, { objectType: ObjectType.EXTRASOLAR, parentId: '', epoch: 0 }),
			systemId: STAR_ID,
			star: STAR(muKm3S2),
			planet: null
		};
	}

	function planetEnd(
		number: number,
		a: number,
		n: number,
		muKm3S2: number | null = STAR_MU
	): ExtrasolarEnd {
		const id = `${STAR_ID}-b-${number}`;
		const body = row(id, { a, n, i: 89.7, om: 40, w: 10, ma: 30 * number, e: 0.005 });
		return {
			body,
			systemId: STAR_ID,
			star: STAR(muKm3S2),
			planet: {
				elements: { a, e: 0.005, i: 89.7, om: 40, w: 10, ma: 30 * number, n, epoch: 2457000 },
				orbitKnown: true,
				size: {
					muKm3S2: 4e5,
					massBasis: 'measured',
					radiusKm: 6500,
					radiusBasis: 'measured'
				},
				class: 'planet',
				classBasis: 'true mass',
				rocky: true
			}
		};
	}

	const B = planetEnd(1, 0.01154, 238.28025);
	const E = planetEnd(4, 0.02925, 59.00659);
	const AT_STAR = starEnd();

	/** The trip as the panel puts it together. */
	function planned(from: ExtrasolarEnd, to: ExtrasolarEnd) {
		const starMu = to.star.muKm3S2 ?? from.star.muKm3S2;
		const plan = transferPlan(from.body, to.body, NO_LOOKUP, starMu);
		const frame = transferFrame(plan);
		return {
			plan,
			frame,
			origin: extrasolarTravelBody(from, frame.centralMu)!,
			target: extrasolarTravelBody(to, frame.centralMu)!,
			centerId: transferCenterId(plan, from.body, to.body, NO_LOOKUP)!
		};
	}

	const requestOf = (trip: ReturnType<typeof planned>): WindowRequest => ({
		origin: trip.origin,
		target: trip.target,
		nowJd: NOW_,
		timeMode: 'now',
		systemPrimary: trip.frame.systemPrimary,
		centralMu: trip.frame.centralMu,
		orbitChange: trip.frame.orbitChange
	});

	function search(
		trip: ReturnType<typeof planned>,
		terms: Pick<RouteOptions, 'departureMode' | 'arrivalMode' | 'departureOrbit' | 'targetOrbit'>
	) {
		const window = searchWindow({ ...requestOf(trip), ...terms })!;
		const options = { ...window, ...terms };
		const grid = computePorkchop(trip.origin, trip.target, options);
		return { grid, routes: selectRoutes(grid, trip.origin, trip.target, options) };
	}

	const ORBIT_TO_ORBIT = { departureMode: 'orbit', arrivalMode: 'low-orbit' } as const;

	/** Every leg of `routes` costs a finite Δv and takes a positive time. */
	function expectFlyable(route: { totalDvKms: number; tofDays: number } | null) {
		expect(route).not.toBeNull();
		expect(Number.isFinite(route!.totalDvKms)).toBe(true);
		expect(route!.tofDays).toBeGreaterThan(0);
	}

	describe('between two planets', () => {
		const trip = planned(B, E);

		it('takes the μ of the star and stays in its frame', () => {
			expect(trip.plan).toEqual({ kind: 'sibling', centreId: STAR_ID, centralMu: STAR_MU });
			expect(trip.frame.orbit).toBe('own');
			expect(trip.centerId).toBe(STAR_ID);
		});

		it('sizes its window by the star, in days and not years', () => {
			const window = searchWindow({
				origin: trip.origin,
				target: trip.target,
				nowJd: NOW_,
				timeMode: 'now',
				centralMu: trip.frame.centralMu
			})!;
			expect(window.departToJd - window.departFromJd).toBeLessThan(4);
			expect(window.tofMaxDays).toBeLessThan(10);
		});

		it('offers Lambert routes that take days', () => {
			const { routes } = search(trip, ORBIT_TO_ORBIT);
			expect(routes.length).toBeGreaterThan(0);
			for (const { route } of routes) {
				expectFlyable(route);
				expect(route.tofDays).toBeLessThan(10);
			}
		});

		it('flies a held drive and a spiral', () => {
			const options = { ...ORBIT_TO_ORBIT, centralMu: trip.frame.centralMu };
			expectFlyable(buildConstantThrustRoute(trip.origin, trip.target, NOW_, G, options));
			expectFlyable(buildLowThrustRoute(trip.origin, trip.target, NOW_, DAWN, options));
		});

		it('draws the arc about the star, between the two planets', () => {
			const { routes } = search(trip, ORBIT_TO_ORBIT);
			const { route } = routes[0];
			const options = { centerId: trip.centerId, centralMu: trip.frame.centralMu };
			const path = buildTrajectoryPath(trip.origin, trip.target, route, options)!;
			expect(path.centerId).toBe(STAR_ID);
			const from = elementsToState(trip.origin.elements, route.departJd)!;
			expect(norm(sub(path.arcs[0].points[0], from.r))).toBeLessThan(1);
			for (const point of path.arcs[0].points) expect(norm(point) / AU_KM).toBeLessThan(0.1);
		});

		it('reports none of the hazards of the Sun', () => {
			const { routes } = search(trip, ORBIT_TO_ORBIT);
			const hazards = routeHazards(trip.origin, trip.target, routes[0].route, {
				centerId: trip.centerId,
				centralMu: trip.frame.centralMu
			});
			expect(hazards).toEqual([]);
		});

		it("flies on a planet's period when the mass of the star is unknown", () => {
			const unknown = planned(
				planetEnd(1, 0.01154, 238.28025, null),
				planetEnd(4, 0.02925, 59.00659, null)
			);
			expect(unknown.plan).toMatchObject({ kind: 'sibling', centreId: STAR_ID });
			const mu = unknown.frame.centralMu! / STAR_MU;
			expect(mu).toBeGreaterThan(0.8);
			expect(mu).toBeLessThan(1.2);
			expect(search(unknown, ORBIT_TO_ORBIT).routes.length).toBeGreaterThan(0);
		});
	});

	describe('between a star and its own planet', () => {
		const out = planned(AT_STAR, B);
		const home = planned(B, AT_STAR);

		it('keeps the frame on the star, with the star as the primary', () => {
			expect(out.plan).toEqual({ kind: 'system', primary: 'origin', centralMu: STAR_MU });
			expect(home.plan).toEqual({ kind: 'system', primary: 'target', centralMu: STAR_MU });
			expect(out.centerId).toBe(STAR_ID);
			expect(home.centerId).toBe(STAR_ID);
		});

		it('offers Lambert routes both ways', () => {
			for (const trip of [out, home]) {
				const { routes } = search(trip, ORBIT_TO_ORBIT);
				expect(routes.length).toBeGreaterThan(0);
				for (const { route } of routes) expectFlyable(route);
			}
		});

		it('flies a held drive and a spiral both ways', () => {
			for (const trip of [out, home]) {
				const options = { ...ORBIT_TO_ORBIT, systemPrimary: trip.frame.systemPrimary };
				expectFlyable(buildConstantThrustRoute(trip.origin, trip.target, NOW_, G, options));
				expectFlyable(buildLowThrustRoute(trip.origin, trip.target, NOW_, DAWN, options));
			}
		});

		it('flies at a star of unknown mass on the period of the planet', () => {
			const trip = planned(starEnd(null), planetEnd(1, 0.01154, 238.28025, null));
			expect(trip.origin.mu).toBeCloseTo(trip.frame.centralMu!, 3);
			expect(trip.origin.mu).toBeGreaterThan(0);
			expect(search(trip, ORBIT_TO_ORBIT).routes.length).toBeGreaterThan(0);
		});

		it('takes the mass of the star from the fit of a planet', () => {
			const trip = planned(starEnd(null), B);
			expect(trip.origin.mu).toBe(STAR_MU);
		});

		it('leaves from a custom orbit inside the planet', () => {
			const departureOrbit: EndOrbit = { rPeriKm: 0.005 * AU_KM, rApoKm: 0.005 * AU_KM };
			const { routes } = search(out, { ...ORBIT_TO_ORBIT, departureOrbit });
			expect(routes.length).toBeGreaterThan(0);
			expect(routes[0].route.departureOrbit).toEqual(departureOrbit);
		});

		it('flies a held drive and a spiral from a custom orbit outside the planet', () => {
			const departureOrbit: EndOrbit = { rPeriKm: 5 * AU_KM, rApoKm: 5 * AU_KM };
			const options = { ...ORBIT_TO_ORBIT, departureOrbit, systemPrimary: 'departure' as const };
			expectFlyable(buildConstantThrustRoute(out.origin, out.target, NOW_, G, options));
			expectFlyable(buildLowThrustRoute(out.origin, out.target, NOW_, DAWN, options));
			// The Lambert family has its low point at the orbit, so it has no arc here.
			expect(buildRoute(out.origin, out.target, NOW_, 3, options)).toBeNull();
		});

		it('keeps a search from a custom orbit outside the planet, with no arcs in it', () => {
			const departureOrbit: EndOrbit = { rPeriKm: 5 * AU_KM, rApoKm: 5 * AU_KM };
			const { routes } = search(out, { ...ORBIT_TO_ORBIT, departureOrbit });
			expect(routes).toEqual([]);
		});

		it('grids the whole family of a high orbit, down to its slowest arc', () => {
			const rNear = 0.005 * AU_KM;
			const departureOrbit: EndOrbit = { rPeriKm: rNear, rApoKm: rNear };
			const low = searchWindow({ ...requestOf(out), ...ORBIT_TO_ORBIT })!;
			const high = searchWindow({ ...requestOf(out), ...ORBIT_TO_ORBIT, departureOrbit })!;
			expect(high.tofMaxDays).toBeGreaterThan(low.tofMaxDays);
			const { routes } = search(out, { ...ORBIT_TO_ORBIT, departureOrbit });
			const slowest = Math.max(...routes.map((choice) => choice.route.tofDays));
			expect(slowest).toBeGreaterThan(low.tofMaxDays);
		});

		it('draws the arc from that orbit', () => {
			const rNear = 0.005 * AU_KM;
			const departureOrbit: EndOrbit = { rPeriKm: rNear, rApoKm: rNear };
			const { routes } = search(out, { ...ORBIT_TO_ORBIT, departureOrbit });
			const path = buildTrajectoryPath(out.origin, out.target, routes[0].route, {
				centerId: out.centerId,
				systemPrimary: out.frame.systemPrimary
			})!;
			expect(norm(path.arcs[0].points[0])).toBeCloseTo(rNear, 2);
		});

		// AD Leo has no radius in the catalogue, and its mass comes from its planet.
		it('prices a star with no radius as one with its forecast radius', () => {
			const end = (of: ExtrasolarEnd): ExtrasolarEnd => ({
				...of,
				star: { ...of.star, radiusKm: null }
			});
			const trip = planned(end(AT_STAR), end(B));
			const star = trip.origin;
			expect(star.radiusKm).toBeGreaterThan(50_000);
			const { routes } = search(trip, ORBIT_TO_ORBIT);
			const cheapest = Math.min(...routes.map((choice) => choice.route.totalDvKms));
			const measured = search(out, ORBIT_TO_ORBIT).routes;
			expect(cheapest).toBeGreaterThan(100);
			expect(cheapest).toBeLessThan(
				1.5 * Math.min(...measured.map((choice) => choice.route.totalDvKms))
			);
		});
	});

	describe('at one body', () => {
		const trip = planned(AT_STAR, AT_STAR);
		const wide: EndOrbit = { rPeriKm: 1000 * AU_KM, rApoKm: 1000 * AU_KM };

		it('joins two orbits of the star, out to 1000 au', () => {
			expect(trip.plan).toEqual({ kind: 'orbit-change' });
			expect(trip.centerId).toBe(STAR_ID);
			const { routes } = search(trip, {
				departureMode: 'orbit',
				arrivalMode: 'low-orbit',
				targetOrbit: wide
			});
			expect(routes.length).toBeGreaterThan(0);
			for (const { route } of routes) expectFlyable(route);
			expect(Math.max(...routes.map(({ route }) => route.tofDays)) / 365.25).toBeGreaterThan(1e4);
		});

		it('joins two orbits of a planet', () => {
			const { routes } = search(planned(B, B), {
				departureMode: 'orbit',
				arrivalMode: 'low-orbit',
				departureOrbit: { rPeriKm: 7000, rApoKm: 7000 },
				targetOrbit: { rPeriKm: 20_000, rApoKm: 20_000 }
			});
			expect(routes.length).toBeGreaterThan(0);
		});
	});

	it('offers the star what the Sun offers, and every planet its own orbits', () => {
		const facts: OrbitFacts = { isStar: true, noPole: true };
		const kinds = (body: TravelBody, end: OrbitFacts, role: 'origin' | 'target') =>
			orbitChoices(body, end, role, { hasSurface: false, customAltKm: 1000 }).map((c) => c.kind);
		const { origin, target } = planned(AT_STAR, B);
		expect(kinds(origin, facts, 'origin')).toEqual(['low-orbit', 'custom']);
		expect(kinds(target, { noPole: true }, 'target')).toEqual(
			expect.arrayContaining(['low-orbit', 'custom', 'flyby'])
		);
	});
});
