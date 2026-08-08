import { describe, it, expect } from 'vitest';
import {
	checkFeasibility,
	feasibleRoutes,
	isLowThrust,
	payloadForC3,
	type Vehicle
} from './vehicles';
import { buildRoute } from './route';
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

const window = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
const tof = hohmannTransferDays(EARTH, MARS)!;
const marsRoute = buildRoute(EARTH, MARS, window, tof)!;

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

	it('declines to judge a constant-acceleration drive at all', () => {
		const torch: Vehicle = {
			id: 'torch',
			kind: 'fictional',
			propulsion: 'fictional',
			status: 'fictional',
			accelMs2: { value: 3.27, source: 't' }
		};
		expect(checkFeasibility(torch, marsRoute).status).toBe('not-modelled');
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

describe('feasibleRoutes', () => {
	it('keeps only what the vehicle can fly', () => {
		const cheap = buildRoute(EARTH, MARS, window, tof, { departureMode: 'orbit' })!;
		const dear = buildRoute(EARTH, JUPITER, window, 500, { departureMode: 'orbit' })!;
		const kept = feasibleRoutes(CRAFT, [cheap, dear]);
		expect(kept).toContain(cheap);
		expect(kept).not.toContain(dear);
	});
});
