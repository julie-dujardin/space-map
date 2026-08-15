import { describe, it, expect } from 'vitest';
import { AU_KM } from '$lib/math/units';
import { equatorialTiltDeg, estimateMu, escapeSpeed, sphereOfInfluenceKm } from './body';
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

describe('equatorialTiltDeg', () => {
	it('measures a direction against the body\u2019s own equator', () => {
		// Earth's pole leans by the obliquity, so the ecliptic's own north stands
		// that much short of square in Earth's equator, and Earth's pole is square.
		expect(equatorialTiltDeg(EARTH, [0, 0, 1])!).toBeCloseTo(90 - 23.44, 1);
		expect(equatorialTiltDeg(EARTH, EARTH.poleEcliptic!)!).toBeCloseTo(90, 6);
		// The equinox lies in both equators at once, so it is no tilt at all —
		// whichever way along it you look.
		expect(equatorialTiltDeg(EARTH, [1, 0, 0])!).toBeCloseTo(0, 6);
		expect(equatorialTiltDeg(EARTH, [-1, 0, 0])!).toBeCloseTo(0, 6);
	});

	it('is unsigned: a southward arc is as steep as a northward one', () => {
		expect(equatorialTiltDeg(EARTH, [0, 0, -1])!).toBeCloseTo(
			equatorialTiltDeg(EARTH, [0, 0, 1])!,
			9
		);
	});

	it('cannot say anything without a pole, or about nowhere', () => {
		expect(equatorialTiltDeg({ ...EARTH, poleEcliptic: undefined }, [0, 0, 1])).toBeUndefined();
		expect(equatorialTiltDeg(EARTH, [0, 0, 0])).toBeUndefined();
	});
});
