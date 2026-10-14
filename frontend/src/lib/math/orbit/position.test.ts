import { describe, it, expect } from 'vitest';
import { ELLIPTIC_ORBITS, EMB, CATALINA_HYP } from './test-helpers';

import { orbitalElementsToPosition, orbitalElementsToPositionJD } from './position';
import { AU_KM, kmToScene } from '$lib/math/units';
import { tdbToUtc } from '$lib/time/jd';

const AU_SCALE = 10;

describe('orbitalElementsToPosition', () => {
	it.each(ELLIPTIC_ORBITS)('returns finite position for $name', ({ el }) => {
		const pos = orbitalElementsToPosition(el);
		expect(pos).not.toBeNull();
		expect(pos!.every(isFinite)).toBe(true);
	});

	it('Earth-Moon Barycenter is near 1 AU from origin', () => {
		const pos = orbitalElementsToPosition(EMB)!;
		const r = Math.sqrt(pos[0] ** 2 + pos[1] ** 2 + pos[2] ** 2) / AU_SCALE;
		expect(r).toBeGreaterThan(0.95);
		expect(r).toBeLessThan(1.05);
	});

	it('returns finite position for Catalina (hyperbolic)', () => {
		const pos = orbitalElementsToPosition(CATALINA_HYP);
		expect(pos).not.toBeNull();
	});
});

describe('orbitalElementsToPositionJD — time scale of the epoch', () => {
	// A circle in Earth's equator, at mean anomaly 0 on its epoch: on the +X axis then.
	const EPOCH = 2461327.5;
	const circle = {
		a: 6778 / AU_KM,
		e: 0,
		i: 0,
		om: 0,
		w: 0,
		ma: 0,
		n: 15.5 * 360,
		epoch: EPOCH
	};
	/** Kilometres off the +X axis. */
	const offAxisKm = (p: [number, number, number] | null) => Math.hypot(p![1], p![2]) / kmToScene(1);

	it('reads the epoch of TLE elements in UTC, like the clock', () => {
		const p = orbitalElementsToPositionJD({ ...circle, equatorial: true }, EPOCH);
		expect(offAxisKm(p)).toBeLessThan(0.01);
	});

	it('reads the epoch of other elements in TDB', () => {
		const p = orbitalElementsToPositionJD(circle, tdbToUtc(EPOCH));
		expect(offAxisKm(p)).toBeLessThan(0.01);
	});
});
