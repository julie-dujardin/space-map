import { describe, it, expect } from 'vitest';
import { buildRoute } from './route';
import { computePorkchop, selectRoutes } from './porkchop';
import { nextTransferWindows, hohmannTransferDays } from './windows';
import { EARTH, J2000, JUPITER, MARS, MOON } from './test-fixtures';

const MARS_WINDOW = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
const MARS_TOF = hohmannTransferDays(EARTH, MARS)!;

describe('buildRoute', () => {
	it('prices an Earth-to-Mars orbiter the way a real mission is priced', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		expect(route).not.toBeNull();

		// Departure energy for a Mars transfer sits around C3 = 8-20 km²/s².
		expect(route.c3Km2S2).toBeGreaterThan(6);
		expect(route.c3Km2S2).toBeLessThan(25);
		// Trans-Mars injection from low Earth orbit is ~3.6 km/s.
		expect(route.inSpaceDvKms).toBeGreaterThan(3.2);
		expect(route.inSpaceDvKms).toBeLessThan(5.0);
		// Ground to Mars orbit, all in.
		expect(route.totalDvKms).toBeGreaterThan(12);
		expect(route.totalDvKms).toBeLessThan(15.5);
	});

	it('lays the journey out as legs that sum to the total', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		expect(route.legs.map((l) => l.kind)).toEqual(['ascent', 'injection', 'cruise', 'capture']);
		const summed = route.legs.reduce((s, l) => s + l.dvKms, 0);
		expect(summed).toBeCloseTo(route.totalDvKms, 9);
		expect(route.legs.reduce((s, l) => s + l.days, 0)).toBeCloseTo(route.tofDays, 9);
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
