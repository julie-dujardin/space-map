import { describe, it, expect } from 'vitest';
import { AU_KM } from '$lib/math/units';
import { estimateMu, escapeSpeed, sphereOfInfluenceKm } from './body';
import { GM_SUN_KM3_S2 } from './constants';
import { EARTH, MARS, MOON } from './test-fixtures';

describe('estimateMu', () => {
	it('recovers a measured GM when given the real density', () => {
		// Earth's mean density is 5514 kg/m³; the estimate should land on its GM.
		expect(estimateMu(EARTH.radiusKm, 5514) / EARTH.mu).toBeCloseTo(1, 2);
	});

	it('scales with the cube of radius', () => {
		expect(estimateMu(20) / estimateMu(10)).toBeCloseTo(8, 9);
	});
});

// The published values for escape speed and sphere of influence live in
// benchmarks.test.ts; these cover the behaviour around them.
describe('escapeSpeed', () => {
	it('is the circular speed scaled by root two', () => {
		expect(escapeSpeed(EARTH)).toBeCloseTo(Math.SQRT2 * Math.sqrt(EARTH.mu / EARTH.radiusKm), 9);
	});

	it('ranks bodies by how hard they are to escape', () => {
		expect(escapeSpeed(MOON)).toBeLessThan(escapeSpeed(MARS));
		expect(escapeSpeed(MARS)).toBeLessThan(escapeSpeed(EARTH));
	});
});

describe('sphereOfInfluenceKm', () => {
	it('grows with distance from the primary', () => {
		const near = sphereOfInfluenceKm(EARTH, GM_SUN_KM3_S2, AU_KM);
		const far = sphereOfInfluenceKm(EARTH, GM_SUN_KM3_S2, 2 * AU_KM);
		expect(far).toBeGreaterThan(near);
	});

	it('is unbounded without a primary to be dominated by', () => {
		expect(sphereOfInfluenceKm(EARTH, 0, AU_KM)).toBe(Infinity);
	});
});
