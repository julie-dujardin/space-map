import { describe, expect, it } from 'vitest';
import type { Vehicle } from '$lib/math/travel';
import { craftBudgetKms, craftReach } from './subway-reach';
import type { Tree, TreeRow } from './subway-tree';

const leg = (dvKms: number, aero = false) => ({ dvKms, aero });

const stop = (kind: 'surface' | 'orbit' | 'escape' | 'transfer', bodyId: string) => ({
	station: `${kind}:${bodyId}`,
	kind,
	bodyId,
	name: bodyId,
	color: 'currentColor',
	mode: null
});

/** Earth's trunk with one destination that brakes in an atmosphere and one
 *  moon hanging off its intercept: the three places a budget can run out. */
function tree(): Tree {
	const moon: TreeRow = {
		targetId: 'moon',
		name: 'moon',
		color: 'currentColor',
		bound: false,
		trunkIndex: 2,
		stationary: false,
		depart: leg(0.4),
		stops: [stop('escape', 'moon'), stop('orbit', 'moon')],
		legs: [leg(0.5)],
		totals: { orbitKms: 0, surfaceKms: null, aeroOrbitKms: null, aeroSurfaceKms: null },
		moons: []
	};
	const mars: TreeRow = {
		targetId: 'mars',
		name: 'mars',
		color: 'currentColor',
		bound: false,
		trunkIndex: 2,
		stationary: false,
		depart: leg(0.6),
		stops: [stop('transfer', 'mars'), stop('escape', 'mars'), stop('orbit', 'mars')],
		legs: [leg(0.7, true), leg(1.4, true)],
		// Braking pays for all but 0.1 of the two arrival burns.
		totals: { orbitKms: 13, surfaceKms: null, aeroOrbitKms: 11.1, aeroSurfaceKms: null },
		moons: [moon]
	};
	return {
		originId: 'earth',
		originName: 'earth',
		trunk: [stop('surface', 'earth'), stop('orbit', 'earth'), stop('escape', 'earth')],
		trunkEnd: null,
		trunkLegs: [leg(9.4), leg(3.2)],
		rows: [mars]
	};
}

const craft = (v: Partial<Vehicle>): Vehicle =>
	({ id: 'x', kind: 'probe', propulsion: 'chemical', status: 'active', ...v }) as Vehicle;

describe('craftBudgetKms', () => {
	it('reads a published budget, and refuses one the map cannot weigh', () => {
		expect(craftBudgetKms(craft({ dvKms: 3.5 }))).toBe(3.5);
		expect(craftBudgetKms(craft({ unlimitedDv: true }))).toBe(Infinity);
		expect(craftBudgetKms(craft({ kind: 'launcher' }))).toBeNull();
	});
});

describe('craftReach', () => {
	it('counts from the parking orbit, not the ground', () => {
		// 0.1 km/s buys nothing, and still stands on the launch pad it was lifted
		// off: ascent is the launcher's bill.
		const reach = craftReach(tree(), craft({ dvKms: 0.1 }))!;
		expect([...reach.stops].sort()).toEqual(['orbit:earth', 'surface:earth']);
	});

	it('stops where the budget does', () => {
		const reach = craftReach(tree(), craft({ dvKms: 3.9, capabilities: ['docking'] }))!;
		// 3.2 to escape, 0.6 more to the intercept; the 0.7 capture is out of reach.
		expect(reach.stops.has('transfer:mars')).toBe(true);
		expect(reach.stops.has('escape:mars')).toBe(false);
		expect(reach.stops.has('orbit:moon')).toBe(false);
	});

	it('spends an atmosphere where the craft has something to fly it behind', () => {
		// 3.2 + 0.6 + 0.7 + 1.4 is 5.9 the hard way, 4.0 with the braking pass.
		const braking = craftReach(tree(), craft({ dvKms: 4.1 }))!;
		expect(braking.stops.has('orbit:mars')).toBe(true);
		const bare = craftReach(tree(), craft({ dvKms: 4.1, capabilities: ['docking'] }))!;
		expect(bare.stops.has('orbit:mars')).toBe(false);
	});

	it('hangs a moon off the intercept its planet shares with it', () => {
		// 3.8 to the intercept, then the moon's own 0.4 and 0.5.
		const reach = craftReach(tree(), craft({ dvKms: 4.2, capabilities: ['docking'] }))!;
		expect(reach.stops.has('escape:moon')).toBe(true);
		expect(reach.stops.has('orbit:moon')).toBe(false);
	});

	it('reaches everything when propellant is no constraint', () => {
		const reach = craftReach(tree(), craft({ unlimitedDv: true }))!;
		expect(reach.stops.has('orbit:moon')).toBe(true);
		expect(reach.budgetKms).toBe(Infinity);
	});

	it('greys nothing out for a craft it cannot weigh', () => {
		expect(craftReach(tree(), craft({ kind: 'launcher' }))).toBeNull();
	});
});
