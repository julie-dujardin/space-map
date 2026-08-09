import { describe, it, expect } from 'vitest';
import {
	canDepartFrom,
	checkFeasibility,
	checkManifest,
	constantThrustAccelMs2,
	crewCapacity,
	dvWithPayloadKms,
	feasibleRoutes,
	isLowThrust,
	payloadForC3,
	type Vehicle
} from './vehicles';
import { buildRoute } from './route';
import { buildConstantThrustRoute } from './brachistochrone';
import { nextTransferWindows, hohmannTransferDays } from './windows';
import { EARTH, J2000, JUPITER, MARS } from './test-fixtures';

const LAUNCHER: Vehicle = {
	id: 'test-launcher',
	kind: 'launcher',
	propulsion: 'chemical',
	status: 'active',
	c3Curve: {
		points: [
			[0, 10000],
			[20, 6000],
			[40, 2000]
		],
		source: 'test',
		truncated: false
	}
};

/** Enough Δv for a Mars transfer (~4.1 km/s in space), nowhere near Jupiter. */
const CRAFT: Vehicle = {
	id: 'test-craft',
	kind: 'probe',
	propulsion: 'chemical',
	status: 'active',
	dvKms: 4.5
};

/** Masses and an engine behind the Δv, so cargo can be priced against them:
 *  320 s through a 4:1 mass ratio is 4.35 km/s empty. */
const HAULER: Vehicle = {
	...CRAFT,
	dryMassKg: { value: 2000, source: 't' },
	propellantMassKg: { value: 6000, source: 't' },
	ispS: { value: 320, source: 't' },
	dvKms: 4.351
};

/** An acceleration and no Δv at all, which is how fiction states a torch drive. */
const TORCH: Vehicle = {
	id: 'test-torch',
	kind: 'fictional',
	propulsion: 'fictional',
	status: 'fictional',
	accelMs2: { value: 3.27, source: 't' },
	unlimitedDv: true
};

const window = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
const tof = hohmannTransferDays(EARTH, MARS)!;
const marsRoute = buildRoute(EARTH, MARS, window, tof)!;

describe('canDepartFrom', () => {
	const pad: Vehicle = { ...LAUNCHER, departsFrom: ['surface'] };
	const capsule: Vehicle = { ...CRAFT, departsFrom: ['orbit'] };
	const both: Vehicle = { ...CRAFT, departsFrom: ['surface', 'orbit'] };
	const rover: Vehicle = { ...CRAFT, departsFrom: [] };

	it('holds a launcher to the ground and a capsule to orbit', () => {
		expect(canDepartFrom(pad, 'surface')).toBe(true);
		expect(canDepartFrom(pad, 'orbit')).toBe(false);
		expect(canDepartFrom(capsule, 'orbit')).toBe(true);
		expect(canDepartFrom(capsule, 'surface')).toBe(false);
	});

	it('lets a craft that lands and lifts off do either', () => {
		expect(canDepartFrom(both, 'surface')).toBe(true);
		expect(canDepartFrom(both, 'orbit')).toBe(true);
	});

	it('reads an empty list as a claim: a rover starts no trip', () => {
		expect(canDepartFrom(rover, 'surface')).toBe(false);
		expect(canDepartFrom(rover, 'orbit')).toBe(false);
	});

	it('reads a missing list as an older export, not as a refusal', () => {
		// The field is absent from exports predating it. Filtering every vehicle
		// out of the picker would be a worse failure than offering a bad one.
		expect(canDepartFrom(CRAFT, 'surface')).toBe(true);
		expect(canDepartFrom(CRAFT, 'orbit')).toBe(true);
	});

	it('fails a route before its Δv is even weighed', () => {
		// A trip this craft could easily afford, from a place it cannot leave.
		const fromGround = buildRoute(EARTH, MARS, window, tof, { departureMode: 'surface' })!;
		expect(checkFeasibility(capsule, fromGround).status).toBe('wrong-departure');
		const fromOrbit = buildRoute(EARTH, MARS, window, tof, { departureMode: 'orbit' })!;
		expect(checkFeasibility(capsule, fromOrbit).status).toBe('ok');
	});

	it('outranks the low-thrust verdict, which is about a different question', () => {
		const ion: Vehicle = { ...CRAFT, propulsion: 'electric', departsFrom: ['orbit'] };
		const fromGround = buildRoute(EARTH, MARS, window, tof, { departureMode: 'surface' })!;
		expect(checkFeasibility(ion, fromGround).status).toBe('wrong-departure');
	});
});

describe('payloadForC3', () => {
	it('interpolates between curve points', () => {
		expect(payloadForC3(LAUNCHER, 10)).toBeCloseTo(8000, 9);
		expect(payloadForC3(LAUNCHER, 30)).toBeCloseTo(4000, 9);
	});

	it('holds the first value below the curve start', () => {
		expect(payloadForC3(LAUNCHER, -5)).toBe(10000);
	});

	it('returns null past the end of the curve', () => {
		expect(payloadForC3(LAUNCHER, 50)).toBeNull();
	});

	it('returns null for a vehicle with no curve', () => {
		expect(payloadForC3(CRAFT, 10)).toBeNull();
	});
});

describe('isLowThrust', () => {
	it('measures acceleration when thrust and mass are both known', () => {
		const ion: Vehicle = {
			...CRAFT,
			propulsion: 'electric',
			dryMassKg: { value: 793, source: 't' },
			propellantMassKg: { value: 425, source: 't' },
			thrustN: { value: 0.092, source: 't' }
		};
		expect(isLowThrust(ion)).toBe(true);
	});

	it('does not call a chemical main engine low-thrust', () => {
		const bipropellant: Vehicle = {
			...CRAFT,
			dryMassKg: { value: 2125, source: 't' },
			propellantMassKg: { value: 3129, source: 't' },
			thrustN: { value: 490, source: 't' }
		};
		expect(isLowThrust(bipropellant)).toBe(false);
	});

	it('falls back to the propulsion type when there is no thrust figure', () => {
		expect(isLowThrust({ ...CRAFT, propulsion: 'electric' })).toBe(true);
		expect(isLowThrust(CRAFT)).toBe(false);
	});
});

describe('checkFeasibility', () => {
	it('passes a launcher that can reach the departure energy, with a payload', () => {
		const result = checkFeasibility(LAUNCHER, marsRoute);
		expect(result.status).toBe('ok');
		expect(result.payloadKg).toBeGreaterThan(0);
	});

	it('fails a launcher on a trajectory past the end of its curve', () => {
		const route = buildRoute(EARTH, JUPITER, window, 500)!;
		expect(checkFeasibility(LAUNCHER, route).status).toBe('over-c3');
	});

	it('separates a truncated curve from a rocket that has run out', () => {
		// Past the end of a curve nobody published far enough is unknown, not
		// impossible — a different answer and a different sentence.
		const partial: Vehicle = {
			...LAUNCHER,
			c3Curve: { ...LAUNCHER.c3Curve!, truncated: true }
		};
		const route = buildRoute(EARTH, JUPITER, window, 500)!;
		expect(checkFeasibility(partial, route).status).toBe('beyond-published');
	});

	it('declines to judge a launcher with no published curve', () => {
		const opaque: Vehicle = { ...LAUNCHER, c3Curve: undefined };
		expect(checkFeasibility(opaque, marsRoute).status).toBe('unknown');
	});

	it('judges a spacecraft on in-space Δv and reports the margin', () => {
		const result = checkFeasibility(CRAFT, marsRoute);
		expect(result.marginKms).toBeCloseTo(CRAFT.dvKms! - marsRoute.inSpaceDvKms, 9);
		expect(result.status).toBe(result.marginKms >= 0 ? 'ok' : 'insufficient-dv');
	});

	it('fails a spacecraft without the Δv', () => {
		const weak: Vehicle = { ...CRAFT, dvKms: 0.5 };
		expect(checkFeasibility(weak, marsRoute).status).toBe('insufficient-dv');
	});

	it('declines to judge a spacecraft whose Δv could not be derived', () => {
		const unknown: Vehicle = { ...CRAFT, dvKms: undefined };
		expect(checkFeasibility(unknown, marsRoute).status).toBe('unknown');
	});

	it('declines to judge a low-thrust vehicle on impulsive Δv', () => {
		const electric: Vehicle = { ...CRAFT, propulsion: 'electric', dvKms: 11 };
		expect(checkFeasibility(electric, marsRoute).status).toBe('not-modelled');
	});

	it('lets a craft whose propellant is not a constraint fly the coasting routes', () => {
		// The whole point of the flag: with no Δv to weigh, nothing is out of reach.
		const jupiter = buildRoute(EARTH, JUPITER, window, 500)!;
		expect(checkFeasibility(TORCH, marsRoute).status).toBe('ok');
		expect(checkFeasibility(TORCH, jupiter).status).toBe('ok');
	});

	it('passes a constant-acceleration drive on the arc it actually flies', () => {
		const arc = buildConstantThrustRoute(EARTH, MARS, J2000, 3.27, { departureMode: 'orbit' })!;
		expect(checkFeasibility(TORCH, arc).status).toBe('ok');
	});

	it('declines to fly a constant-thrust arc with anything that has no drive to hold', () => {
		const arc = buildConstantThrustRoute(EARTH, MARS, J2000, 3.27, { departureMode: 'orbit' })!;
		expect(checkFeasibility({ ...CRAFT, dvKms: 5000 }, arc).status).toBe('not-modelled');
	});

	// A sail publishes an acceleration it cannot hold: true at one distance and
	// falling off as the inverse square. Having one is not permission to fly an arc.
	it('declines an arc to an acceleration whose craft still has a propellant story', () => {
		const sail: Vehicle = {
			id: 'test-sail',
			kind: 'fictional',
			propulsion: 'solar-sail',
			status: 'concept',
			accelMs2: { value: 0.0002, source: 't' }
		};
		expect(constantThrustAccelMs2(sail)).toBeUndefined();
		const arc = buildConstantThrustRoute(EARTH, MARS, J2000, 3.27, { departureMode: 'orbit' })!;
		expect(checkFeasibility(sail, arc).status).toBe('not-modelled');
	});

	it('still flags a constant-thrust trip that outlasts the consumables', () => {
		const slow = buildConstantThrustRoute(EARTH, MARS, J2000, 0.002, { departureMode: 'orbit' })!;
		const crewed: Vehicle = { ...TORCH, enduranceDays: { value: 30, source: 't' } };
		const result = checkFeasibility(crewed, slow);
		expect(result.status).toBe('ok');
		expect(result.enduranceRatio).toBeGreaterThan(1);
	});

	it('flags a trip that outlasts the consumables without failing it', () => {
		const capsule: Vehicle = {
			...CRAFT,
			kind: 'crewed',
			enduranceDays: { value: 21, source: 't' }
		};
		const result = checkFeasibility(capsule, marsRoute);
		expect(result.status).toBe('ok');
		expect(result.enduranceRatio).toBeGreaterThan(1);
	});

	it('flags an arrival faster than the heat shield is rated for', () => {
		const landing = buildRoute(EARTH, MARS, window, tof, { arrivalMode: 'landing' })!;
		const shielded: Vehicle = {
			...CRAFT,
			maxEntrySpeedKms: { value: 0.1, source: 't' }
		};
		expect(checkFeasibility(shielded, landing).overEntrySpeedKms).toBeGreaterThan(0.1);
	});
});

describe('crewCapacity', () => {
	it('reads a published figure', () => {
		expect(crewCapacity({ ...CRAFT, crew: { value: 4, source: 't' } })).toBe(4);
	});

	it('seats nobody on a vehicle that carries nobody', () => {
		expect(crewCapacity(CRAFT)).toBe(0);
		expect(crewCapacity(LAUNCHER)).toBe(0);
	});

	it('leaves a crewed vehicle unjudged when no source says', () => {
		expect(crewCapacity({ ...CRAFT, kind: 'crewed' })).toBeNull();
	});
});

describe('dvWithPayloadKms', () => {
	it('leaves an empty hold at the published figure', () => {
		expect(dvWithPayloadKms(HAULER, 0)).toBe(HAULER.dvKms);
	});

	it('spends the mass ratio on the cargo', () => {
		// 320 s through 9 t over 3 t, against 8 over 2 empty.
		expect(dvWithPayloadKms(HAULER, 1000)).toBeCloseTo(3.448, 3);
	});

	it('keeps a figure it cannot re-derive rather than going silent', () => {
		expect(dvWithPayloadKms(CRAFT, 1000)).toBe(CRAFT.dvKms);
	});
});

describe('checkManifest', () => {
	const CAPSULE: Vehicle = { ...CRAFT, kind: 'crewed', crew: { value: 4, source: 't' } };

	it('takes a party that fits', () => {
		expect(checkManifest(CAPSULE, { passengers: 4, payloadKg: 0 }).status).toBe('ok');
	});

	it('reports the seats when there are not enough', () => {
		expect(checkManifest(CAPSULE, { passengers: 5, payloadKg: 0 })).toEqual({
			status: 'over-capacity',
			seats: 4
		});
	});

	it('refuses people on a craft with no seats at all', () => {
		expect(checkManifest(CRAFT, { passengers: 1, payloadKg: 0 }).status).toBe('over-capacity');
	});

	it('declines to judge a crewed craft whose complement is unpublished', () => {
		const opaque: Vehicle = { ...CRAFT, kind: 'crewed' };
		expect(checkManifest(opaque, { passengers: 2, payloadKg: 0 }).status).toBe('unknown-capacity');
	});

	// The pipeline does not state a hold yet; the check is inert until it does
	// rather than assuming one.
	it('ignores cargo until a hold is published', () => {
		expect(checkManifest(CRAFT, { passengers: 0, payloadKg: 9e6 }).status).toBe('ok');
	});

	it('reports the hold when the cargo is over it', () => {
		const held: Vehicle = { ...CRAFT, payloadCapacityKg: { value: 800, source: 't' } };
		expect(checkManifest(held, { passengers: 0, payloadKg: 900 })).toEqual({
			status: 'over-payload',
			capacityKg: 800
		});
	});
});

describe('checkFeasibility with a manifest', () => {
	it('takes the cargo out of the margin', () => {
		const empty = checkFeasibility(HAULER, marsRoute).marginKms;
		const laden = checkFeasibility(HAULER, marsRoute, { passengers: 0, payloadKg: 500 }).marginKms;
		expect(laden).toBeLessThan(empty);
	});

	it('turns a route the craft could fly empty into one it cannot', () => {
		expect(checkFeasibility(HAULER, marsRoute).status).toBe('ok');
		const laden = checkFeasibility(HAULER, marsRoute, { passengers: 0, payloadKg: 1000 });
		expect(laden.status).toBe('insufficient-dv');
	});

	// A crewed vehicle's dry mass already carries its seats and consumables, and
	// no source prices one more passenger.
	it('does not weigh the passengers', () => {
		const crewed = checkFeasibility(HAULER, marsRoute, { passengers: 3, payloadKg: 0 });
		expect(crewed.marginKms).toBe(checkFeasibility(HAULER, marsRoute).marginKms);
	});

	it('fails a launcher asked to send more than its curve allows', () => {
		const capacity = payloadForC3(LAUNCHER, marsRoute.c3Km2S2)!;
		const over = checkFeasibility(LAUNCHER, marsRoute, {
			passengers: 0,
			payloadKg: capacity + 1
		});
		expect(over.status).toBe('over-payload');
		// The capacity travels with the verdict — it is the whole answer.
		expect(over.payloadKg).toBeCloseTo(capacity, 9);
	});

	it('passes a launcher whose curve covers the cargo', () => {
		const capacity = payloadForC3(LAUNCHER, marsRoute.c3Km2S2)!;
		const under = { passengers: 0, payloadKg: capacity - 1 };
		expect(checkFeasibility(LAUNCHER, marsRoute, under).status).toBe('ok');
	});
});

describe('feasibleRoutes', () => {
	it('keeps only what the vehicle can fly', () => {
		const cheap = buildRoute(EARTH, MARS, window, tof, { departureMode: 'orbit' })!;
		const dear = buildRoute(EARTH, JUPITER, window, 500, { departureMode: 'orbit' })!;
		const kept = feasibleRoutes(CRAFT, [cheap, dear]);
		expect(kept).toContain(cheap);
		expect(kept).not.toContain(dear);
	});
});
