import { describe, it, expect } from 'vitest';
import { checkFeasibility, feasibleRoutes, payloadForC3, type Vehicle } from './vehicles';
import { buildRoute } from './route';
import { nextTransferWindows, hohmannTransferDays } from './windows';
import { EARTH, J2000, JUPITER, MARS } from './test-fixtures';

const LAUNCHER: Vehicle = {
	id: 'test-launcher',
	kind: 'launcher',
	propulsion: 'chemical',
	dvKms: 0,
	c3Curve: [
		[0, 10000],
		[20, 6000],
		[40, 2000]
	]
};

/** Enough Δv for a Mars transfer (~4.1 km/s in space), nowhere near Jupiter. */
const CRAFT: Vehicle = { id: 'test-craft', kind: 'probe', propulsion: 'chemical', dvKms: 4.5 };

const window = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
const tof = hohmannTransferDays(EARTH, MARS)!;

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

describe('checkFeasibility', () => {
	it('passes a launcher that can reach the departure energy, with a payload', () => {
		const route = buildRoute(EARTH, MARS, window, tof)!;
		const result = checkFeasibility(LAUNCHER, route);
		expect(result.status).toBe('ok');
		expect(result.payloadKg).toBeGreaterThan(0);
	});

	it('fails a launcher on a trajectory past the end of its curve', () => {
		const route = buildRoute(EARTH, JUPITER, window, 500)!;
		expect(checkFeasibility(LAUNCHER, route).status).toBe('over-c3');
	});

	it('judges a spacecraft on in-space Δv and reports the margin', () => {
		const route = buildRoute(EARTH, MARS, window, tof)!;
		const result = checkFeasibility(CRAFT, route);
		expect(result.marginKms).toBeCloseTo(CRAFT.dvKms - route.inSpaceDvKms, 9);
		expect(result.status).toBe(result.marginKms >= 0 ? 'ok' : 'insufficient-dv');
	});

	it('fails a spacecraft without the Δv', () => {
		const route = buildRoute(EARTH, MARS, window, tof)!;
		const weak: Vehicle = { ...CRAFT, dvKms: 0.5 };
		expect(checkFeasibility(weak, route).status).toBe('insufficient-dv');
	});

	it('declines to judge a low-thrust vehicle on impulsive Δv', () => {
		const route = buildRoute(EARTH, MARS, window, tof)!;
		const electric: Vehicle = { ...CRAFT, propulsion: 'electric', dvKms: 11, lowThrust: true };
		expect(checkFeasibility(electric, route).status).toBe('not-modelled');
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
