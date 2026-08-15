import { describe, it, expect } from 'vitest';
import { buildRoute, routeDurationDays, type Route } from './route';
import { ascentDv } from './maneuvers';
import { computePorkchop, selectRoutes } from './porkchop';
import { nextTransferWindows, hohmannTransferDays } from './windows';
import { EARTH, J2000, JUPITER, MARS, MOON, PARABOLIC_COMET } from './test-fixtures';

const MARS_WINDOW = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
const MARS_TOF = hohmannTransferDays(EARTH, MARS)!;

/** The launch leg of a route, km/s. */
function ascentOf(route: Route): number {
	return route.legs.find((leg) => leg.kind === 'ascent')!.dvKms;
}

describe('buildRoute', () => {
	it('prices an Earth-to-Mars orbiter the way a real mission is priced', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		expect(route).not.toBeNull();

		// Departure energy for a Mars transfer sits around C3 = 8-20 km²/s².
		expect(route.c3Km2S2).toBeGreaterThan(6);
		expect(route.c3Km2S2).toBeLessThan(25);
		// Trans-Mars injection from low Earth orbit is ~3.6 km/s, and an orbit
		// insertion burnt on the engine is another 1-2 on top.
		expect(route.inSpaceDvKms).toBeGreaterThan(4.5);
		expect(route.inSpaceDvKms).toBeLessThan(7.0);
		// Ground to Mars orbit, all in.
		expect(route.totalDvKms).toBeGreaterThan(13);
		expect(route.totalDvKms).toBeLessThan(17);
	});

	it('charges a launch for the latitude it leaves from', () => {
		const equator = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { departureSiteLatDeg: 0 })!;
		const polar = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { departureSiteLatDeg: 85 })!;
		const unplaced = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;

		// A trip that never says where it leaves from prices as the equatorial
		// launch the ascent estimate is fitted on, so nothing published moves.
		expect(ascentOf(unplaced)).toBeCloseTo(ascentDv(EARTH), 12);
		expect(ascentOf(polar)).toBeGreaterThan(ascentOf(equator));
		// Nothing after the launch changes: where it left from is not the arc's
		// business.
		expect(polar.inSpaceDvKms).toBeCloseTo(equator.inSpaceDvKms, 12);
	});

	it('charges an equatorial pad for an arc that leaves out of the equator', () => {
		// The plane has to hold the asymptote as well as reach the pad, so a pad
		// on the equator is not thereby free.
		const flat = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { departureSiteLatDeg: 0 })!;
		expect(ascentOf(flat)).toBeGreaterThan(ascentDv(EARTH));
		// A Mars departure leaves near the ecliptic, which is already a score of
		// degrees out of Earth's equator — real, and still under a tenth of a km/s.
		expect(ascentOf(flat) - ascentDv(EARTH)).toBeLessThan(0.1);
		// Without a pole there is no equator to be tilted against, and only the
		// pad's own latitude is left to charge for.
		const poleless = { ...EARTH, poleEcliptic: undefined };
		const blind = buildRoute(poleless, MARS, MARS_WINDOW, MARS_TOF, { departureSiteLatDeg: 0 })!;
		expect(ascentOf(blind)).toBeCloseTo(ascentDv(EARTH), 12);
	});

	it('leaves the atmosphere out of it unless asked', () => {
		const propulsive = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		const aero = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { aero: 'aerocapture' })!;
		expect(propulsive.entrySpeedKms).toBeUndefined();
		expect(aero.inSpaceDvKms).toBeLessThan(propulsive.inSpaceDvKms);
	});

	it('trades the insertion burn for months when aerobraking', () => {
		const options = { arrivalMode: 'low-orbit' } as const;
		const propulsive = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, options)!;
		const braked = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			...options,
			aero: 'aerobraking'
		})!;

		// The engine still captures; what drag saves is the circularization after.
		expect(braked.inSpaceDvKms).toBeLessThan(propulsive.inSpaceDvKms - 1);
		// Every flown Mars campaign ran between two and ten months.
		const campaign = braked.legs.find((l) => l.kind === 'aerobrake')!;
		expect(campaign.dvKms).toBe(0);
		expect(campaign.days).toBeGreaterThan(60);
		expect(campaign.days).toBeLessThan(300);
		// The crossing is unchanged — the campaign happens after arrival.
		expect(routeDurationDays(braked)).toBeCloseTo(braked.tofDays + campaign.days, 9);
	});

	it('lands straight off the approach when the atmosphere can be flown', () => {
		const options = { arrivalMode: 'landing' } as const;
		const direct = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			...options,
			aero: 'aerocapture'
		})!;
		// Viking and every Mars lander since entered from the arrival hyperbola
		// without ever being in orbit, so there is no insertion to pay for.
		expect(direct.legs.map((l) => l.kind)).not.toContain('capture');
		expect(direct.entrySpeedKms).toBeGreaterThan(direct.vInfArrKms);
	});

	it('lays the journey out as legs that sum to the total', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		expect(route.legs.map((l) => l.kind)).toEqual(['ascent', 'injection', 'cruise', 'capture']);
		const summed = route.legs.reduce((s, l) => s + l.dvKms, 0);
		expect(summed).toBeCloseTo(route.totalDvKms, 9);
		expect(route.legs.reduce((s, l) => s + l.days, 0)).toBeCloseTo(route.tofDays, 9);
	});

	it('prices an arc to a parabolic comet', () => {
		// C/1264 N1 is seven centuries past perihelion and hundreds of AU out, so
		// the cruise is measured in centuries — absurd, but the honest answer.
		const route = buildRoute(EARTH, PARABOLIC_COMET, J2000 + 9000, 200 * 365.25)!;
		expect(route).not.toBeNull();
		expect(route.totalDvKms).toBeGreaterThan(0);
		expect(isFinite(route.c3Km2S2)).toBe(true);
	});

	it('adds a descent leg only when landing', () => {
		const orbit = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'capture' })!;
		const land = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		expect(orbit.legs.some((l) => l.kind === 'descent')).toBe(false);
		expect(land.legs.some((l) => l.kind === 'descent')).toBe(true);
		expect(land.totalDvKms).toBeGreaterThan(orbit.totalDvKms);
	});

	it('drops the capture leg for a flyby, making it the cheapest arrival', () => {
		const flyby = buildRoute(EARTH, JUPITER, MARS_WINDOW, 900, { arrivalMode: 'flyby' })!;
		const capture = buildRoute(EARTH, JUPITER, MARS_WINDOW, 900, { arrivalMode: 'capture' })!;
		expect(flyby.legs.some((l) => l.kind === 'capture')).toBe(false);
		expect(flyby.totalDvKms).toBeLessThan(capture.totalDvKms);
	});

	it('charges nothing for ascent when already in orbit', () => {
		const surface = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { departureMode: 'surface' })!;
		const orbit = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { departureMode: 'orbit' })!;
		expect(orbit.totalDvKms).toBeCloseTo(orbit.inSpaceDvKms, 9);
		expect(surface.totalDvKms).toBeGreaterThan(orbit.totalDvKms);
		expect(surface.inSpaceDvKms).toBeCloseTo(orbit.inSpaceDvKms, 9);
	});

	it('makes Jupiter cost more to reach than Mars', () => {
		const mars = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'flyby' })!;
		const jupiter = buildRoute(EARTH, JUPITER, MARS_WINDOW, 900, { arrivalMode: 'flyby' })!;
		expect(jupiter.totalDvKms).toBeGreaterThan(mars.totalDvKms);
	});

	it('is symmetric in the direction of travel for a flyby', () => {
		// The same arc flown the other way needs the same heliocentric energy;
		// only the endpoint bodies change what it costs to get on and off it.
		const out = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'flyby' })!;
		const back = buildRoute(MARS, EARTH, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'flyby'
		})!;
		expect(back).not.toBeNull();
		expect(out.tofDays).toBe(back.tofDays);
	});

	it('rejects a non-positive time of flight', () => {
		expect(buildRoute(EARTH, MARS, MARS_WINDOW, 0)).toBeNull();
		expect(buildRoute(EARTH, MARS, MARS_WINDOW, -10)).toBeNull();
	});

	it('handles a departure body with no atmosphere', () => {
		const route = buildRoute(MOON, MARS, MARS_WINDOW, MARS_TOF, { departureMode: 'surface' });
		expect(route).not.toBeNull();
		expect(isFinite(route!.totalDvKms)).toBe(true);
	});
});

describe('computePorkchop', () => {
	const grid = computePorkchop(EARTH, MARS, {
		departFromJd: MARS_WINDOW - 60,
		departToJd: MARS_WINDOW + 60,
		tofMinDays: 120,
		tofMaxDays: 400,
		departSteps: 40,
		tofSteps: 40
	});

	it('solves most of the grid', () => {
		expect(grid.solvedCount).toBeGreaterThan(0.9 * grid.departSteps * grid.tofSteps);
	});

	it('finds a minimum near the analytic transfer cost', () => {
		let min = Infinity;
		for (const dv of grid.totalDvKms) if (isFinite(dv) && dv < min) min = dv;
		expect(min).toBeGreaterThan(12);
		expect(min).toBeLessThan(14.5);
	});

	it('lays the axes out as requested', () => {
		expect(grid.departJds).toHaveLength(40);
		expect(grid.tofDays).toHaveLength(40);
		expect(grid.tofDays[0]).toBeCloseTo(120, 9);
		expect(grid.tofDays[39]).toBeCloseTo(400, 9);
		expect(grid.totalDvKms).toHaveLength(1600);
	});
});

describe('selectRoutes', () => {
	const grid = computePorkchop(EARTH, MARS, {
		departFromJd: MARS_WINDOW - 90,
		departToJd: MARS_WINDOW + 90,
		tofMinDays: 100,
		tofMaxDays: 450,
		departSteps: 50,
		tofSteps: 50
	});
	const routes = selectRoutes(grid, EARTH, MARS);

	it('offers up to three distinct profiles', () => {
		expect(routes.length).toBeGreaterThan(0);
		expect(routes.length).toBeLessThanOrEqual(3);
		expect(new Set(routes.map((r) => r.profile)).size).toBe(routes.length);
	});

	it('makes the fast route arrive sooner and the efficient one cost less', () => {
		const fast = routes.find((r) => r.profile === 'fast');
		const efficient = routes.find((r) => r.profile === 'efficient');
		if (!fast || !efficient) return;
		expect(fast.route.arriveJd).toBeLessThanOrEqual(efficient.route.arriveJd);
		expect(efficient.route.totalDvKms).toBeLessThanOrEqual(fast.route.totalDvKms);
	});

	it('puts the balanced route between the other two', () => {
		const byProfile = Object.fromEntries(routes.map((r) => [r.profile, r.route]));
		const { fast, balanced, efficient } = byProfile;
		if (!fast || !balanced || !efficient) return;
		expect(balanced.totalDvKms).toBeLessThanOrEqual(fast.totalDvKms);
		expect(balanced.totalDvKms).toBeGreaterThanOrEqual(efficient.totalDvKms);
		expect(balanced.arriveJd).toBeGreaterThanOrEqual(fast.arriveJd);
		expect(balanced.arriveJd).toBeLessThanOrEqual(efficient.arriveJd);
	});

	it('refines below the grid resolution', () => {
		// The polished route must be no worse than the best raw cell.
		let min = Infinity;
		for (const dv of grid.totalDvKms) if (isFinite(dv) && dv < min) min = dv;
		const efficient = routes.find((r) => r.profile === 'efficient')!;
		expect(efficient.route.totalDvKms).toBeLessThanOrEqual(min + 1e-9);
	});

	it('returns nothing when the grid has no solutions', () => {
		const empty = computePorkchop(EARTH, MARS, {
			departFromJd: MARS_WINDOW,
			departToJd: MARS_WINDOW,
			tofMinDays: -5,
			tofMaxDays: -5,
			departSteps: 2,
			tofSteps: 2
		});
		expect(selectRoutes(empty, EARTH, MARS)).toEqual([]);
	});
});

describe('selectRoutes under an arrival deadline', () => {
	const options = {
		departFromJd: MARS_WINDOW - 90,
		departToJd: MARS_WINDOW + 90,
		tofMinDays: 100,
		tofMaxDays: 450,
		departSteps: 50,
		tofSteps: 50
	};
	const grid = computePorkchop(EARTH, MARS, options);
	// Tight enough to rule out the cheap corner of the field, which is where the
	// unconstrained efficient route lives.
	const deadlineJd = MARS_WINDOW + 150;
	const routes = selectRoutes(grid, EARTH, MARS, { ...options, deadlineJd });

	it('offers only routes that arrive in time', () => {
		expect(routes.length).toBeGreaterThan(0);
		for (const { route } of routes) expect(route.arriveJd).toBeLessThanOrEqual(deadlineJd);
	});

	// The bug this replaced: the three profiles were picked off the whole field
	// and the late ones then dropped, so a deadline cost you the choice rather
	// than moving it.
	it('re-picks inside the deadline rather than dropping what misses it', () => {
		const dropped = selectRoutes(grid, EARTH, MARS).filter(
			(choice) => choice.route.arriveJd <= deadlineJd
		);
		expect(routes.length).toBeGreaterThan(dropped.length);
		const cheapest = Math.min(...routes.map((r) => r.route.totalDvKms));
		const wasCheapest = Math.min(...dropped.map((r) => r.route.totalDvKms));
		expect(cheapest).toBeLessThan(wasCheapest);
	});

	// The polish chases Δv alone, and cost falls off towards a later arrival.
	it('keeps the refinement inside the deadline', () => {
		const efficient = routes.find((r) => r.profile === 'efficient')!;
		expect(efficient.route.arriveJd).toBeLessThanOrEqual(deadlineJd);
	});

	it('offers nothing when no cell arrives in time', () => {
		expect(selectRoutes(grid, EARTH, MARS, { ...options, deadlineJd: MARS_WINDOW })).toEqual([]);
	});
});
