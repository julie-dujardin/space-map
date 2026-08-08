/**
 * A trip between two moons of one planet, end to end: search bounds, grid,
 * offered routes.
 *
 * This is the case the planner used to refuse outright. It is not special
 * geometry — both ends orbit Jupiter the way Earth and Mars orbit the Sun, so it
 * is the same Lambert solve with a different mass at the focus. What it does
 * break is every bound stated in bare days: Io to Europa is a 1.3-day crossing
 * with a 3.5-day synodic period, so a 60-day floor grids seventeen windows at
 * once and a 15-day cruise floor asks for arcs that are ten transfers long.
 */

import { describe, it, expect } from 'vitest';
import { computePorkchop, hohmannTransferDays, selectRoutes } from '$lib/math/travel';
import { EUROPA, IO, JUPITER, MARS, EARTH } from '$lib/math/travel/test-fixtures';
import { searchWindow } from './search-window';

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

	// The floors were absolute before, and they still must not move a trip that
	// really is months long.
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
