import { describe, it, expect } from 'vitest';
import { buildAssistRoute, findAssistRoute } from './assist';
import { computePorkchop, selectRoutes } from './porkchop';
import { EARTH, ESCAPING_PROBE, J2000, JUPITER, MARS, SATURN, VENUS } from './test-fixtures';
import { hohmannTransferDays } from './windows';

/** A departure in the app's own era rather than at the elements' epoch. */
const NOW = 2461080.5;

/** The cheapest direct route over the same era, to compare an assist against. */
function cheapestDirect(
	from: typeof EARTH,
	to: typeof EARTH,
	options: Record<string, unknown> = {}
) {
	const hohmann = hohmannTransferDays(from, to)!;
	const grid = computePorkchop(from, to, {
		departFromJd: NOW,
		departToJd: NOW + 3 * 365.25,
		tofMinDays: hohmann * 0.3,
		tofMaxDays: hohmann * 2,
		departSteps: 60,
		tofSteps: 60,
		departureMode: 'orbit',
		...options
	});
	const routes = selectRoutes(grid, from, to, { departureMode: 'orbit', ...options });
	return routes.find((choice) => choice.profile === 'efficient')!.route;
}

describe('buildAssistRoute', () => {
	it('lays out two cruises around the pass, and they sum', () => {
		const route = buildAssistRoute(EARTH, JUPITER, SATURN, NOW, 900, 1400, {
			departureMode: 'surface',
			arrivalMode: 'landing'
		})!;
		expect(route.legs.map((leg) => leg.kind)).toEqual([
			'ascent',
			'injection',
			'cruise',
			'assist',
			'cruise',
			'capture',
			'descent'
		]);
		expect(route.legs.reduce((sum, leg) => sum + leg.dvKms, 0)).toBeCloseTo(route.totalDvKms, 9);
		expect(route.legs.reduce((sum, leg) => sum + leg.days, 0)).toBeCloseTo(route.tofDays, 9);
	});

	it('reports the pass it flew', () => {
		const route = buildAssistRoute(EARTH, JUPITER, SATURN, NOW, 900, 1400, {
			departureMode: 'orbit'
		})!;
		const [pass] = route.flybys!;
		expect(pass.bodyId).toBe(JUPITER.id);
		expect(pass.jd).toBeCloseTo(NOW + 900, 9);
		expect(pass.altitudeKm).toBeGreaterThan(0);
		// The Δv the pass could not supply is charged as a leg, so the two agree.
		expect(route.legs.find((leg) => leg.kind === 'assist')!.dvKms).toBeCloseTo(pass.dvKms, 12);
	});

	it('ends at the target on the date the two cruises add up to', () => {
		const route = buildAssistRoute(EARTH, JUPITER, SATURN, NOW, 900, 1400, {
			departureMode: 'orbit'
		})!;
		expect(route.departureId).toBe(EARTH.id);
		expect(route.targetId).toBe(SATURN.id);
		expect(route.tofDays).toBeCloseTo(2300, 9);
		expect(route.arriveJd).toBeCloseTo(NOW + 2300, 9);
	});

	it('refuses a leg with no time in it', () => {
		expect(buildAssistRoute(EARTH, JUPITER, SATURN, NOW, 0, 1400)).toBeNull();
		expect(buildAssistRoute(EARTH, JUPITER, SATURN, NOW, 900, -1)).toBeNull();
	});

	it('refuses a pass the body cannot bend', () => {
		// Straight past Mars at interplanetary speed on a pair of arcs that need a
		// large turn between them: there is no periapsis above the ground that does it.
		expect(buildAssistRoute(EARTH, MARS, SATURN, NOW, 60, 200)).toBeNull();
	});
});

describe('findAssistRoute', () => {
	it('gets to Saturn past Jupiter for less than going straight there', () => {
		const direct = cheapestDirect(EARTH, SATURN);
		const assist = findAssistRoute(EARTH, SATURN, [JUPITER, VENUS, MARS], {
			nowJd: NOW,
			departureMode: 'orbit'
		})!;
		expect(assist).not.toBeNull();
		expect(assist.flybys![0].bodyId).toBe(JUPITER.id);
		expect(assist.totalDvKms).toBeLessThan(direct.totalDvKms);
		// And it arrives far slower than it, which is the trade being made.
		expect(assist.tofDays).toBeGreaterThan(direct.tofDays);
	});

	it('takes the pass for free when it can', () => {
		const assist = findAssistRoute(EARTH, SATURN, [JUPITER], {
			nowJd: NOW,
			departureMode: 'orbit'
		})!;
		const [pass] = assist.flybys!;
		// Metres per second on a budget of kilometres: the search drives the pass
		// to the free one and stops where the refinement's last step is.
		expect(pass.dvKms).toBeLessThan(0.02);
		// Nothing but direction changes across an unpowered pass.
		expect(pass.vInfOutKms / pass.vInfInKms).toBeCloseTo(1, 2);
		expect(pass.turnDeg).toBeGreaterThan(20);
	});

	it('arrives slower than a direct route does, which is where the saving is', () => {
		const direct = cheapestDirect(EARTH, SATURN);
		const assist = findAssistRoute(EARTH, SATURN, [JUPITER], {
			nowJd: NOW,
			departureMode: 'orbit'
		})!;
		expect(assist.vInfArrKms).toBeLessThan(direct.vInfArrKms);
	});

	it('will not swing past either end of the trip', () => {
		expect(findAssistRoute(EARTH, SATURN, [EARTH, SATURN], { nowJd: NOW })).toBeNull();
	});

	it('has no window to seed on when the swing-by body never comes round', () => {
		expect(
			findAssistRoute(EARTH, SATURN, [ESCAPING_PROBE], { nowJd: NOW, departureMode: 'orbit' })
		).toBeNull();
	});

	// The seeds come from the departure and the swing-by body, both of which come
	// round; where the target goes afterwards only sets the second leg's scale.
	it('still swings by for a target that never comes round', () => {
		const assist = findAssistRoute(EARTH, ESCAPING_PROBE, [JUPITER], {
			nowJd: NOW,
			departureMode: 'orbit'
		});
		expect(assist?.flybys?.[0]?.bodyId).toBe(JUPITER.id);
	});

	it('never departs before now, however far ahead it looks', () => {
		const assist = findAssistRoute(EARTH, SATURN, [JUPITER], {
			nowJd: NOW,
			departureMode: 'orbit'
		})!;
		expect(assist.departJd).toBeGreaterThanOrEqual(NOW);
	});

	it('finds nothing inside a horizon with no window in it', () => {
		expect(
			findAssistRoute(EARTH, SATURN, [JUPITER], {
				nowJd: J2000,
				horizonDays: 30,
				departureMode: 'orbit'
			})
		).toBeNull();
	});

	// The hunt ranks on Δv over twenty years, so without a deadline it can answer
	// with a departure well past one the caller actually needs.
	describe('under an arrival deadline', () => {
		it('arrives by it', () => {
			const deadlineJd = NOW + 12 * 365.25;
			const assist = findAssistRoute(EARTH, SATURN, [JUPITER], {
				nowJd: NOW,
				deadlineJd,
				departureMode: 'orbit'
			});
			expect(assist).not.toBeNull();
			expect(assist!.arriveJd).toBeLessThanOrEqual(deadlineJd);
		});

		it('gives up rather than overshooting when nothing fits', () => {
			expect(
				findAssistRoute(EARTH, SATURN, [JUPITER], {
					nowJd: NOW,
					deadlineJd: NOW + 200,
					departureMode: 'orbit'
				})
			).toBeNull();
		});

		it('takes a departure date as a floor to leave after', () => {
			const earliestJd = NOW + 4 * 365.25;
			const assist = findAssistRoute(EARTH, SATURN, [JUPITER], {
				nowJd: earliestJd,
				departureMode: 'orbit'
			})!;
			expect(assist.departJd).toBeGreaterThanOrEqual(earliestJd);
		});
	});
});
