import { describe, expect, it } from 'vitest';
import {
	buildConstantThrustRoute,
	buildInterstellarTorchRoute,
	buildRoute,
	GM_SUN_KM3_S2,
	type SystemEnd,
	type TravelBody
} from '$lib/math/travel';
import { EARTH_BARYCENTRIC, J2000, MOON_BARYCENTRIC } from '$lib/math/travel/test-fixtures';
import { LIGHT_YEAR_KM } from '$lib/math/units';
import { arrivalSpeedKms } from './arrival-stats';

/** A red dwarf and a planet of it, on a circle of 0.03 au. */
const STAR: TravelBody = {
	id: 'x-1',
	mu: 0.09 * GM_SUN_KM3_S2,
	muEstimated: true,
	radiusKm: 83_000,
	elements: { a: 0, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0, epoch: J2000 }
};
const PLANET: TravelBody = {
	id: 'x-1-b-1',
	mu: 3e5,
	muEstimated: true,
	radiusKm: 5_800,
	parentId: STAR.id,
	elements: { a: 0.03, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 59, epoch: J2000 }
};

const TO_ORBIT = { departureMode: 'orbit', arrivalMode: 'low-orbit' } as const;

describe('arrivalSpeedKms', () => {
	it('has no figure on the way down to a primary', () => {
		const inward = { ...TO_ORBIT, systemPrimary: 'target' } as const;
		const fromPlanet = buildRoute(PLANET, STAR, J2000, 1, { ...inward, centralMu: STAR.mu })!;
		expect(arrivalSpeedKms(fromPlanet)).toBeNull();
		const fromMoon = buildRoute(MOON_BARYCENTRIC, EARTH_BARYCENTRIC, J2000, 4, inward)!;
		expect(arrivalSpeedKms(fromMoon)).toBeNull();
	});

	it('reads the excess speed at a satellite', () => {
		const outward = { ...TO_ORBIT, systemPrimary: 'departure' } as const;
		const route = buildRoute(STAR, PLANET, J2000, 1, { ...outward, centralMu: STAR.mu })!;
		expect(arrivalSpeedKms(route)).toBe(route.vInfArrKms);
		expect(route.vInfArrKms).toBeGreaterThan(0);
	});

	it('reads the speed of a held arc that comes down to a primary', () => {
		const route = buildConstantThrustRoute(PLANET, STAR, J2000, 9.8, {
			...TO_ORBIT,
			systemPrimary: 'target'
		})!;
		expect(arrivalSpeedKms(route)).toBe(route.vInfArrKms);
	});

	it('reads 0 on a held stop at rest', () => {
		const end = (body: TravelBody, ly: number): SystemEnd => ({
			body,
			starKm: [ly * LIGHT_YEAR_KM, 0, 0],
			starMu: body.mu,
			atStar: true
		});
		const route = buildInterstellarTorchRoute(end(STAR, 0), end(STAR, 4), J2000, 9.8, {
			departureMode: 'rendezvous',
			arrivalMode: 'rendezvous'
		})!;
		expect(arrivalSpeedKms(route)).toBe(0);
	});
});
