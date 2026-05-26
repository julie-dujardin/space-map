import { describe, it, expect, beforeEach } from 'vitest';
import { Vector3 } from 'three';
import { evaluateEclipseFactor, getEclipseSceneUniforms } from './eclipse-shadow';

/**
 * Contract tests for the CPU port of the GLSL `eclipseFactor()` in
 * `eclipse-shadow.ts`. The fragment shader and `evaluateEclipseFactor` must
 * agree on these values — any change to one path requires updating the
 * other and verifying these cases still pass.
 */

function resetUniforms(): void {
	const u = getEclipseSceneUniforms();
	u.uSunDir.value.set(1, 0, 0);
	u.uSunAngularRadius.value = 0;
	u.uOccluderCount.value = 0;
	for (const o of u.uOccluders.value) o.set(0, 0, 0, 0);
}

function setSun(angularRadius: number, dir: [number, number, number] = [1, 0, 0]): void {
	const u = getEclipseSceneUniforms();
	u.uSunDir.value.set(...dir).normalize();
	u.uSunAngularRadius.value = angularRadius;
}

function setOccluders(occluders: { pos: [number, number, number]; r: number }[]): void {
	const u = getEclipseSceneUniforms();
	u.uOccluderCount.value = occluders.length;
	for (let i = 0; i < occluders.length; i++) {
		u.uOccluders.value[i].set(...occluders[i].pos, occluders[i].r);
	}
}

const ORIGIN = new Vector3(0, 0, 0);

describe('evaluateEclipseFactor', () => {
	beforeEach(resetUniforms);

	it('returns 1 when sun is disabled', () => {
		setSun(0);
		setOccluders([{ pos: [10, 0, 0], r: 5 }]);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(1);
	});

	it('returns 1 with no occluders', () => {
		setSun(0.005);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(1);
	});

	it('returns 1 when occluder is behind the receiver (away from sun)', () => {
		setSun(0.005, [1, 0, 0]);
		setOccluders([{ pos: [-10, 0, 0], r: 1 }]);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(1);
	});

	it('returns 0 when a large occluder fully covers the sun head-on (chord regime)', () => {
		// Earth-like at LEO: aOc ≈ 1.2 rad, aSun ≈ 0.005 rad → chord regime.
		setSun(0.005, [1, 0, 0]);
		setOccluders([{ pos: [6378, 0, 0], r: 6378 }]); // along +sunDir
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(0);
	});

	it('returns 0 when occluder fully covers the sun head-on (lens regime total)', () => {
		// Comparable angular sizes, occluder slightly bigger and dead-on.
		setSun(0.005, [1, 0, 0]);
		setOccluders([{ pos: [100, 0, 0], r: 1 }]); // aOc ≈ 0.01 rad
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(0);
	});

	it('produces correct annular factor (small occluder dead-on)', () => {
		// Occluder fully inside sun disc: factor = 1 - (aOc/aSun)^2.
		setSun(0.01, [1, 0, 0]);
		// aOc = asin(1/1000) ≈ 0.001 rad → ratio² = 0.01
		setOccluders([{ pos: [1000, 0, 0], r: 1 }]);
		const f = evaluateEclipseFactor(ORIGIN, ORIGIN);
		expect(f).toBeCloseTo(0.99, 4);
	});

	it('produces correct chord factor at half-cover (t=0)', () => {
		// Chord regime, occluder limb passes through sun center → exactly half covered.
		// sep == aOc → t = 0 → covered = (acos(0) + 0)/π = 0.5 → factor = 0.5.
		const aSun = 0.005;
		const aOc = 1.0; // > 10 * aSun
		const dOc = 1 / Math.sin(aOc); // so asin(r/dOc) = aOc, with r = 1
		// Place occluder at angle = aOc from sun direction → sep = aOc.
		setSun(aSun, [1, 0, 0]);
		const cosA = Math.cos(aOc);
		const sinA = Math.sin(aOc);
		setOccluders([{ pos: [dOc * cosA, dOc * sinA, 0], r: 1 }]);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBeCloseTo(0.5, 6);
	});

	it('returns 1 when chord-regime occluder is past the penumbra edge', () => {
		// sep = aOc + aSun + ε → t = -1 - ε/aSun < -1 → continue, no contribution.
		const aSun = 0.005;
		const aOc = 1.0;
		const dOc = 1 / Math.sin(aOc);
		setSun(aSun, [1, 0, 0]);
		const sep = aOc + aSun + 0.001;
		setOccluders([{ pos: [dOc * Math.cos(sep), dOc * Math.sin(sep), 0], r: 1 }]);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(1);
	});

	it('returns 1 when lens-regime occluder is past the penumbra edge', () => {
		// sep ≥ aSun + aOc → continue.
		setSun(0.005, [1, 0, 0]);
		// aOc ≈ 0.005 rad; place at sep = 0.011 rad.
		const dOc = 200;
		const r = dOc * Math.sin(0.005);
		const sep = 0.011;
		setOccluders([{ pos: [dOc * Math.cos(sep), dOc * Math.sin(sep), 0], r }]);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(1);
	});

	it('produces lens-formula factor at half-cover (equal radii, sep = aSun)', () => {
		// Two equal discs offset by one radius → lens area = 2(a²·acos(1/2) - a²·√3/4)
		// = 2a²(π/3 - √3/4); covered fraction = 2(π/3 - √3/4)/π.
		const a = 0.005;
		setSun(a, [1, 0, 0]);
		const dOc = 1000;
		const r = dOc * Math.sin(a); // aOc = a
		const sep = a;
		setOccluders([{ pos: [dOc * Math.cos(sep), dOc * Math.sin(sep), 0], r }]);
		const expected = 1 - (2 * (Math.PI / 3 - Math.sqrt(3) / 4)) / Math.PI;
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBeCloseTo(expected, 5);
	});

	it('multiplies contributions from independent occluders', () => {
		setSun(0.01, [1, 0, 0]);
		// Two small dead-on occluders, each annular at 99% factor.
		setOccluders([
			{ pos: [1000, 0, 0], r: 1 },
			{ pos: [1000, 0, 0], r: 1 }
		]);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBeCloseTo(0.99 * 0.99, 4);
	});

	it('skips the receiver body itself via selfPos', () => {
		setSun(0.005, [1, 0, 0]);
		// Occluder centered on the receiver — without the self-skip it would
		// dim everything; with it, the body is treated as itself.
		const selfPos = new Vector3(500, 0, 0);
		setOccluders([{ pos: [500, 0, 0], r: 100 }]);
		expect(evaluateEclipseFactor(selfPos, selfPos)).toBe(1);
	});

	it('skips zero-radius occluders', () => {
		setSun(0.005, [1, 0, 0]);
		setOccluders([{ pos: [100, 0, 0], r: 0 }]);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(1);
	});
});
