import { describe, it, expect, beforeEach } from 'vitest';
import { Vector3, Vector4 } from 'three';
import type { AtmosphereParams } from './atmosphere';
import {
	atmosphereLeak,
	cullOccludersFor,
	ECLIPSE_LEAK_GAIN,
	evaluateEclipseFactor,
	evaluateEclipseLeak,
	getEclipseSceneUniforms,
	getOccluderPool,
	MAX_OCCLUDERS,
	sunLeak
} from './eclipse-shadow';

/**
 * Contract tests for the CPU ports of the GLSL `eclipseFactorAt` and
 * `eclipseLeakAt`. The shader and these functions must agree on the values.
 */

function resetUniforms(): void {
	const u = getEclipseSceneUniforms();
	u.uSunDir.value.set(1, 0, 0);
	u.uSunAngularRadius.value = 0;
	u.uOccluderCount.value = 0;
	for (const o of u.uOccluders.value) o.set(0, 0, 0, 0);
	for (const o of u.uOccluderLeak.value) o.set(0, 0, 0, 0);
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

/** Air with the Rayleigh numbers of the Earth and no haze. */
function air(overrides: Partial<AtmosphereParams> = {}): AtmosphereParams {
	return {
		topAltitudeKm: 67,
		rayleighScatterPerKm: [0.004848, 0.01149, 0.02871],
		rayleighScaleHeightKm: 8.4,
		mieScatterPerKm: [0, 0, 0],
		mieAbsorptionPerKm: [0, 0, 0],
		mieScaleHeightKm: 1.2,
		miePhase: [],
		absorptionPerKm: [0, 0, 0],
		absorptionCenterKm: 0,
		absorptionWidthKm: 1,
		bakedCompensation: 0,
		multiScatterGain: 1,
		sunIntensity: 1,
		sunColor: [1, 1, 1],
		refractivity: [0.000276, 0.000278, 0.000281],
		...overrides
	};
}

const EARTH_KM = 6371;

describe('atmosphereLeak', () => {
	it('gives the optical depth per radian and the bend at the ground for clear air', () => {
		const leak = atmosphereLeak(air(), EARTH_KM, new Vector4());
		expect(leak.x).toBeCloseTo(146.5, 0);
		expect(leak.y).toBeCloseTo(347.2, 0);
		expect(leak.z).toBeCloseTo(867.5, 0);
		// 66 arc minutes. The textbook value is 70.
		expect(leak.w).toBeCloseTo(0.0192, 4);
	});

	it('is all 0 for air with no refractivity', () => {
		const leak = atmosphereLeak(
			air({ refractivity: undefined }),
			EARTH_KM,
			new Vector4(1, 1, 1, 1)
		);
		expect(leak.toArray()).toEqual([0, 0, 0, 0]);
	});

	it('stops the rays under the level where the haze is opaque', () => {
		const hazy = air({
			mieScatterPerKm: [0.0513, 0.0694, 0.0952],
			mieAbsorptionPerKm: [0.0056, 0.0056, 0.0056]
		});
		const leak = atmosphereLeak(hazy, EARTH_KM, new Vector4());
		// The haze of the Earth is opaque along a ray under 3 km.
		expect(leak.w).toBeCloseTo(0.0192 * Math.exp(-3.03 / 8.4), 4);
		expect(leak.x).toBeCloseTo(146.5, 0);
	});

	it('keeps the bend at the ground under thin haze', () => {
		const leak = atmosphereLeak(
			air({ mieScatterPerKm: [1e-4, 1e-4, 1e-4] }),
			EARTH_KM,
			new Vector4()
		);
		expect(leak.w).toBeCloseTo(0.0192, 4);
	});

	it('lets no ray through haze that is higher than the gas', () => {
		const titan = air({
			rayleighScaleHeightKm: 21.1,
			mieScatterPerKm: [0.079, 0.068, 0.035],
			mieAbsorptionPerKm: [0.0043, 0.049, 0.132],
			mieScaleHeightKm: 60,
			refractivity: [0.00129, 0.0013, 0.00131]
		});
		expect(atmosphereLeak(titan, 2575, new Vector4()).w).toBeLessThan(1e-6);
	});
});

describe('sunLeak', () => {
	// The Earth from the Moon, clear air.
	const A_SUN = 0.0047;
	const A_EARTH = 0.0166;
	const EARTH_AIR = new Vector4(146, 347, 868, 0.0192);
	const out = new Vector3();

	it('is orange at the edge of the umbra', () => {
		sunLeak(A_SUN, A_EARTH, A_EARTH - A_SUN, EARTH_AIR, out);
		expect(out.x).toBeCloseTo(0.503, 3);
		expect(out.y).toBeCloseTo(0.196, 3);
		expect(out.z).toBeCloseTo(0.017, 3);
	});

	it('is deep red at the centre of the umbra', () => {
		sunLeak(A_SUN, A_EARTH, 0, EARTH_AIR, out);
		expect(out.x).toBeCloseTo(0.089, 3);
		expect(out.y).toBeCloseTo(0.003, 3);
		expect(out.z).toBeCloseTo(0, 5);
	});

	it('goes down and gets redder from the edge of the umbra to its centre', () => {
		let last = Infinity;
		let lastRatio = 0;
		for (let sep = A_EARTH - A_SUN; sep >= 0; sep -= 0.001) {
			sunLeak(A_SUN, A_EARTH, sep, EARTH_AIR, out);
			expect(out.x).toBeLessThan(last);
			expect(out.x / out.y).toBeGreaterThan(lastRatio);
			last = out.x;
			lastRatio = out.x / out.y;
		}
	});

	it('is 0 out of the shadow', () => {
		sunLeak(A_SUN, A_EARTH, A_EARTH + A_SUN, EARTH_AIR, out);
		expect(out.toArray()).toEqual([0, 0, 0]);
	});

	it('has no step in the penumbra', () => {
		const step = 1e-7;
		for (let sep = A_EARTH - A_SUN; sep <= A_EARTH + A_SUN; sep += A_SUN / 8) {
			const here = sunLeak(A_SUN, A_EARTH, sep, EARTH_AIR, new Vector3());
			const next = sunLeak(A_SUN, A_EARTH, sep + step, EARTH_AIR, new Vector3());
			expect(here.distanceTo(next)).toBeLessThan(1e-4);
		}
	});

	it('keeps the penumbra grey where the Sun is a quarter in view', () => {
		// f = 0.25 here.
		sunLeak(A_SUN, A_EARTH, A_EARTH - 0.43 * A_SUN, EARTH_AIR, out);
		expect(out.x).toBeLessThan(0.1);
		expect(out.x).toBeGreaterThan(0);
	});

	it('is 0 for an occluder with no air', () => {
		sunLeak(A_SUN, A_EARTH, 0, new Vector4(0, 0, 0, 0), out);
		expect(out.toArray()).toEqual([0, 0, 0]);
	});

	// Jupiter from Io. The largest bend is much less than the angular radius of the planet.
	const A_SUN_JUPITER = 0.00089;
	const A_JUPITER = 0.17;
	const JUPITER_AIR = new Vector4(151, 360, 905, 0.0124);

	it('is 0 where the bend would be over the largest bend', () => {
		const bend = JUPITER_AIR.w + A_SUN_JUPITER;
		sunLeak(A_SUN_JUPITER, A_JUPITER, A_JUPITER - bend, JUPITER_AIR, out);
		expect(out.toArray()).toEqual([0, 0, 0]);
		sunLeak(A_SUN_JUPITER, A_JUPITER, 0, JUPITER_AIR, out);
		expect(out.toArray()).toEqual([0, 0, 0]);
	});

	it('fades across the disc of the Sun at the largest bend', () => {
		sunLeak(A_SUN_JUPITER, A_JUPITER, A_JUPITER - JUPITER_AIR.w, JUPITER_AIR, out);
		expect(out.x).toBeCloseTo(0.5 * Math.exp(-151 * 0.0124), 5);
	});

	it('follows the exponential between the edge of the umbra and the largest bend', () => {
		sunLeak(A_SUN_JUPITER, A_JUPITER, A_JUPITER - 0.005, JUPITER_AIR, out);
		expect(out.x).toBeCloseTo(Math.exp(-151 * 0.005), 6);
		expect(out.y).toBeCloseTo(Math.exp(-360 * 0.005), 6);
		expect(out.z).toBeCloseTo(Math.exp(-905 * 0.005), 6);
	});

	it('stays small in the penumbra of air that bends less than the width of the Sun', () => {
		// Mars from Phobos.
		const aSun = 0.00305;
		const aMars = 0.37;
		const marsAir = new Vector4(316, 752, 1890, 1.56e-4);
		for (let sep = aMars - aSun; sep <= aMars + aSun; sep += aSun / 16) {
			sunLeak(aSun, aMars, sep, marsAir, out);
			expect(out.x).toBeLessThan(0.04);
		}
	});
});

describe('evaluateEclipseLeak', () => {
	beforeEach(resetUniforms);

	const out = new Vector3();
	const A_SUN = 0.0047;
	// The Earth at 60 radii on the line to the Sun. The origin is at the centre of its umbra.
	const EARTH = { pos: [60, 0, 0] as [number, number, number], r: 1 };

	function setAir(index: number, k: [number, number, number], largestBend: number): void {
		getEclipseSceneUniforms().uOccluderLeak.value[index].set(...k, largestBend);
	}

	it('is the leak of the occluder with the display gain', () => {
		setSun(A_SUN);
		setOccluders([EARTH]);
		setAir(0, [146, 347, 868], 0.0192);
		evaluateEclipseLeak(ORIGIN, ORIGIN, out);
		const bend = Math.asin(1 / 60);
		expect(out.x).toBeCloseTo(ECLIPSE_LEAK_GAIN * Math.exp(-146 * bend), 6);
		expect(out.y).toBeCloseTo(ECLIPSE_LEAK_GAIN * Math.exp(-347 * bend), 6);
		expect(evaluateEclipseFactor(ORIGIN, ORIGIN)).toBe(0);
	});

	it('is 0 when no occluder has air', () => {
		setSun(A_SUN);
		setOccluders([EARTH]);
		expect(evaluateEclipseLeak(ORIGIN, ORIGIN, out).toArray()).toEqual([0, 0, 0]);
	});

	it('is 0 when the sun is disabled', () => {
		setSun(0);
		setOccluders([EARTH]);
		setAir(0, [146, 347, 868], 0.0192);
		expect(evaluateEclipseLeak(ORIGIN, ORIGIN, out).toArray()).toEqual([0, 0, 0]);
	});

	it('skips the receiver body itself via selfPos', () => {
		setSun(A_SUN);
		const selfPos = new Vector3(...EARTH.pos);
		setOccluders([EARTH]);
		setAir(0, [146, 347, 868], 0.0192);
		expect(evaluateEclipseLeak(selfPos, selfPos, out).toArray()).toEqual([0, 0, 0]);
	});

	it('adds the leaks of two occluders', () => {
		setSun(A_SUN);
		setOccluders([EARTH, EARTH]);
		setAir(0, [146, 347, 868], 0.0192);
		setAir(1, [146, 347, 868], 0.0192);
		const bend = Math.asin(1 / 60);
		expect(evaluateEclipseLeak(ORIGIN, ORIGIN, out).x).toBeCloseTo(
			2 * ECLIPSE_LEAK_GAIN * Math.exp(-146 * bend),
			6
		);
	});
});

describe('cullOccludersFor', () => {
	beforeEach(resetUniforms);

	function setPool(occluders: { pos: [number, number, number]; r: number }[]): void {
		const pool = getOccluderPool();
		pool.count = occluders.length;
		for (let i = 0; i < occluders.length; i++) {
			pool.occluders[i] ??= new Vector4();
			pool.leaks[i] ??= new Vector4();
			pool.occluders[i].set(...occluders[i].pos, occluders[i].r);
			pool.leaks[i].set(0, 0, 0, 0);
		}
	}

	const slots = () => Array.from({ length: MAX_OCCLUDERS }, () => new Vector4());

	it('keeps the air of an occluder at the index of the occluder', () => {
		setSun(0.0047);
		// The first is far off the line to the Sun. The second is on it.
		setPool([
			{ pos: [60, 500, 0], r: 1 },
			{ pos: [60, 0, 0], r: 1 }
		]);
		getOccluderPool().leaks[1].set(146, 347, 868, 0.0192);
		const dst = slots();
		const leakDst = slots();
		const kept = cullOccludersFor(
			dst,
			ORIGIN,
			0.27,
			getEclipseSceneUniforms().uSunDir.value,
			leakDst
		);
		expect(kept).toBe(1);
		expect(dst[0].toArray()).toEqual([60, 0, 0, 1]);
		expect(leakDst[0].toArray()).toEqual([146, 347, 868, 0.0192]);
	});

	it('keeps the occluders of largest angular radius when too many can reach', () => {
		setSun(0.0047);
		// All on the line to the Sun. The angular radius grows with the index.
		const all = Array.from({ length: MAX_OCCLUDERS + 8 }, (_, i) => ({
			pos: [100 + i, 0, 0] as [number, number, number],
			r: 0.01 * (i + 1)
		}));
		setPool(all);
		const dst = slots();
		const kept = cullOccludersFor(dst, ORIGIN, 1, getEclipseSceneUniforms().uSunDir.value);
		expect(kept).toBe(MAX_OCCLUDERS);
		const radii = dst.map((v) => v.w).sort((a, b) => a - b);
		expect(radii[0]).toBeCloseTo(0.09, 9);
		expect(radii[MAX_OCCLUDERS - 1]).toBeCloseTo(0.4, 9);
	});
});
