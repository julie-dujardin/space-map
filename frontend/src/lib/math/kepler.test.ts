import { describe, it, expect, vi } from 'vitest';
import type { OrbitalElements } from '$lib/types/objects';
import {
	solveKepler,
	solveKeplerHyperbolic,
	solveBarker,
	orbitalElementsToPosition,
	orbitalElementsToEllipse,
	orbitalElementsToParabola,
	orbitalElementsToHyperbola,
	orbitalElementsToCurve
} from './kepler';

// Mock dateToJD so we don't depend on paraglide / real dates
vi.mock('$lib/format/date', () => ({
	dateToJD: (d: Date) => d.getTime() / 86400000 + 2440587.5
}));

// ── Test fixtures ──────────────────────────────────────────────────

/** Earth-like circular orbit for sanity checks. */
const EARTH: OrbitalElements = {
	a: 1.0,
	e: 0.0167,
	i: 0.0,
	om: 0.0,
	w: 102.9,
	ma: 0,
	n: 0.9856,
	epoch: 2451545.0 // J2000
};

/** C/1955 L1 (Mrkos) — high-eccentricity elliptic comet. */
const MRKOS: OrbitalElements = {
	a: 49.54047782041923,
	e: 0.9892134956255171,
	i: 86.5030098745164,
	om: 48.94154652798637,
	w: 32.50623865086751,
	ma: 0.1125983403385835,
	n: 0.002826596307620889,
	epoch: 2435302.5
};

/** A true parabolic orbit (e=1, q-based). */
const PARABOLIC: OrbitalElements = {
	a: 0,
	e: 1.0,
	i: 45.0,
	om: 90.0,
	w: 180.0,
	ma: 0,
	n: 0,
	epoch: 2451545.0,
	q: 1.5,
	tp: 2451545.0
};

/** A hyperbolic orbit. */
const HYPERBOLIC: OrbitalElements = {
	a: -5.0,
	e: 1.2,
	i: 30.0,
	om: 60.0,
	w: 120.0,
	ma: 10.0,
	n: 0.05,
	epoch: 2451545.0
};

// ── Kepler solvers ─────────────────────────────────────────────────

describe('solveKepler', () => {
	it('returns M for circular orbit (e=0)', () => {
		const E = solveKepler(1.0, 0);
		expect(E).toBeCloseTo(1.0, 10);
	});

	it('solves known case e=0.5, M=1', () => {
		const E = solveKepler(1.0, 0.5);
		// Verify: E - e*sin(E) = M
		expect(E - 0.5 * Math.sin(E)).toBeCloseTo(1.0, 10);
	});

	it('solves high-eccentricity e=0.99', () => {
		const E = solveKepler(0.5, 0.99);
		expect(E - 0.99 * Math.sin(E)).toBeCloseTo(0.5, 8);
	});

	it('solves for Mrkos eccentricity', () => {
		const M = MRKOS.ma * (Math.PI / 180);
		const E = solveKepler(M, MRKOS.e);
		expect(E - MRKOS.e * Math.sin(E)).toBeCloseTo(M, 8);
	});
});

describe('solveKeplerHyperbolic', () => {
	it('solves e=1.5 M=1', () => {
		const H = solveKeplerHyperbolic(1.0, 1.5);
		expect(1.5 * Math.sinh(H) - H).toBeCloseTo(1.0, 8);
	});
});

describe('solveBarker', () => {
	it('returns nu=0, r=q at perihelion (t = tp)', () => {
		const result = solveBarker(1.5, 2451545.0, 2451545.0);
		expect(result).not.toBeNull();
		expect(result!.nu).toBeCloseTo(0, 10);
		expect(result!.r).toBeCloseTo(1.5, 10);
	});

	it('produces finite results for large time offsets', () => {
		const result = solveBarker(1.0, 2451545.0, 2451545.0 + 10000);
		expect(result).not.toBeNull();
		expect(isFinite(result!.nu)).toBe(true);
		expect(result!.r).toBeGreaterThan(0);
	});
});

// ── Position computation ───────────────────────────────────────────

describe('orbitalElementsToPosition', () => {
	it('returns non-null for Earth-like orbit', () => {
		const pos = orbitalElementsToPosition(EARTH);
		expect(pos).not.toBeNull();
		// Earth at ~1 AU, scaled by AU_SCALE=10
		const r = Math.sqrt(pos![0] ** 2 + pos![1] ** 2 + pos![2] ** 2);
		expect(r).toBeGreaterThan(8); // ~1 AU * 10
		expect(r).toBeLessThan(12);
	});

	it('returns non-null for Mrkos (high-e elliptic)', () => {
		const pos = orbitalElementsToPosition(MRKOS);
		expect(pos).not.toBeNull();
		expect(pos!.every(isFinite)).toBe(true);
	});

	it('returns non-null for hyperbolic orbit', () => {
		const pos = orbitalElementsToPosition(HYPERBOLIC);
		expect(pos).not.toBeNull();
	});
});

// ── Curve generators ───────────────────────────────────────────────

describe('orbitalElementsToEllipse', () => {
	it('generates correct number of points', () => {
		const pts = orbitalElementsToEllipse(EARTH, 64);
		expect(pts.length).toBe(65); // 0..64 inclusive
	});

	it('all points are finite for Earth', () => {
		const pts = orbitalElementsToEllipse(EARTH, 64);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
	});

	it('all points are finite for Mrkos (e=0.989)', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 128);
		const finite = pts.filter((p) => p.every(isFinite));
		expect(finite.length).toBe(pts.length);
	});

	it('forms a closed loop for Earth (first ≈ last point)', () => {
		const pts = orbitalElementsToEllipse(EARTH, 128);
		const first = pts[0];
		const last = pts[pts.length - 1];
		expect(first[0]).toBeCloseTo(last[0], 3);
		expect(first[1]).toBeCloseTo(last[1], 3);
		expect(first[2]).toBeCloseTo(last[2], 3);
	});

	it('forms a closed loop for Mrkos (first ≈ last point)', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 128);
		const first = pts[0];
		const last = pts[pts.length - 1];
		expect(first[0]).toBeCloseTo(last[0], 3);
		expect(first[1]).toBeCloseTo(last[1], 3);
		expect(first[2]).toBeCloseTo(last[2], 3);
	});

	it('perihelion distance matches q = a(1-e) for Mrkos', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 512);
		// Distance from origin (focus) for each point, in AU (divide by AU_SCALE=10)
		const distances = pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / 10);
		const minDist = Math.min(...distances);
		const expectedQ = MRKOS.a * (1 - MRKOS.e); // ~0.534 AU
		expect(minDist).toBeCloseTo(expectedQ, 1);
	});

	it('aphelion distance matches Q = a(1+e) for Mrkos', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 512);
		const distances = pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / 10);
		const maxDist = Math.max(...distances);
		const expectedQ = MRKOS.a * (1 + MRKOS.e); // ~98.5 AU
		expect(maxDist).toBeCloseTo(expectedQ, 0);
	});
});

describe('orbitalElementsToParabola', () => {
	it('generates points for parabolic orbit', () => {
		const pts = orbitalElementsToParabola(PARABOLIC, 64);
		expect(pts.length).toBe(65);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
	});

	it('minimum distance is close to q', () => {
		const pts = orbitalElementsToParabola(PARABOLIC, 512);
		const distances = pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / 10);
		const minDist = Math.min(...distances);
		expect(minDist).toBeCloseTo(PARABOLIC.q!, 1);
	});
});

describe('orbitalElementsToHyperbola', () => {
	it('generates points for hyperbolic orbit', () => {
		const pts = orbitalElementsToHyperbola(HYPERBOLIC, 64);
		expect(pts.length).toBeGreaterThan(0);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
	});

	it('minimum distance is close to q = |a|(e-1)', () => {
		const pts = orbitalElementsToHyperbola(HYPERBOLIC, 512);
		const distances = pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / 10);
		const minDist = Math.min(...distances);
		const expectedQ = Math.abs(HYPERBOLIC.a) * (HYPERBOLIC.e - 1); // 5 * 0.2 = 1.0
		expect(minDist).toBeCloseTo(expectedQ, 1);
	});
});

// ── Curve dispatcher ───────────────────────────────────────────────

describe('orbitalElementsToEllipse – curve quality', () => {
	it('consecutive points are smoothly spaced (no jumps) for Mrkos', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 512);
		const gaps: number[] = [];
		for (let i = 1; i < pts.length; i++) {
			const d = Math.sqrt(
				(pts[i][0] - pts[i - 1][0]) ** 2 +
					(pts[i][1] - pts[i - 1][1]) ** 2 +
					(pts[i][2] - pts[i - 1][2]) ** 2
			);
			gaps.push(d);
		}
		const maxGap = Math.max(...gaps);
		const minGap = Math.min(...gaps);
		const meanGap = gaps.reduce((a, b) => a + b, 0) / gaps.length;
		// With E-uniform sampling, gaps should be reasonably uniform
		// For high-e orbits the perihelion points are closer, aphelion further, but no single
		// point should be wildly off. Max gap should be < 50x mean gap.
		console.log(
			`Mrkos curve gaps: min=${minGap.toFixed(4)} mean=${meanGap.toFixed(4)} max=${maxGap.toFixed(4)} ratio=${(maxGap / meanGap).toFixed(2)}`
		);
		expect(maxGap / meanGap).toBeLessThan(50);
		// No zero-length segments (duplicate points)
		expect(minGap).toBeGreaterThan(0);
	});

	it('curve points lie on the expected ellipse (r matches orbital mechanics)', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 512);
		const distances = pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / 10);
		const q = MRKOS.a * (1 - MRKOS.e);
		const Q = MRKOS.a * (1 + MRKOS.e);
		// All distances should be between perihelion and aphelion
		for (const r of distances) {
			expect(r).toBeGreaterThanOrEqual(q * 0.99);
			expect(r).toBeLessThanOrEqual(Q * 1.01);
		}
	});

	it('identifies the worst gap in the Mrkos curve', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 512);
		let worstIdx = 0;
		let worstGap = 0;
		for (let i = 1; i < pts.length; i++) {
			const d = Math.sqrt(
				(pts[i][0] - pts[i - 1][0]) ** 2 +
					(pts[i][1] - pts[i - 1][1]) ** 2 +
					(pts[i][2] - pts[i - 1][2]) ** 2
			);
			if (d > worstGap) {
				worstGap = d;
				worstIdx = i;
			}
		}
		const rPrev = Math.sqrt(pts[worstIdx - 1].reduce((s, c) => s + c * c, 0)) / 10;
		const rCurr = Math.sqrt(pts[worstIdx].reduce((s, c) => s + c * c, 0)) / 10;
		console.log(
			`Worst gap at index ${worstIdx}: gap=${worstGap.toFixed(2)} scene units (${(worstGap / 10).toFixed(2)} AU)`
		);
		console.log(
			`  Point ${worstIdx - 1}: [${pts[worstIdx - 1].map((v) => v.toFixed(2)).join(', ')}] r=${rPrev.toFixed(2)} AU`
		);
		console.log(
			`  Point ${worstIdx}: [${pts[worstIdx].map((v) => v.toFixed(2)).join(', ')}] r=${rCurr.toFixed(2)} AU`
		);
		// Eccentric anomaly at these indices
		const E_prev = ((worstIdx - 1) / 512) * 2 * Math.PI;
		const E_curr = (worstIdx / 512) * 2 * Math.PI;
		console.log(
			`  E_prev=${((E_prev * 180) / Math.PI).toFixed(2)}° E_curr=${((E_curr * 180) / Math.PI).toFixed(2)}°`
		);
		expect(worstGap).toBeGreaterThan(0);
	});

	it('reports curve shape stats for Mrkos', () => {
		const pts = orbitalElementsToEllipse(MRKOS, 512);
		const distances = pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / 10);
		const q = MRKOS.a * (1 - MRKOS.e);
		const Q = MRKOS.a * (1 + MRKOS.e);
		console.log(`Mrkos orbit: q=${q.toFixed(3)} AU, Q=${Q.toFixed(3)} AU`);
		console.log(
			`Computed: min_r=${Math.min(...distances).toFixed(3)} AU, max_r=${Math.max(...distances).toFixed(3)} AU`
		);
		console.log(`Points generated: ${pts.length}`);
		// Count how many points are near perihelion (<5 AU) vs near aphelion (>50 AU)
		const nearPeri = distances.filter((r) => r < 5).length;
		const nearAph = distances.filter((r) => r > 50).length;
		console.log(`Near perihelion (<5 AU): ${nearPeri}, near aphelion (>50 AU): ${nearAph}`);
		expect(pts.length).toBe(513);
	});
});

describe('solveKepler – known limitations', () => {
	it('diverges for high-e near perihelion (documents why orbitalElementsToEllipse avoids round-trip)', () => {
		// With e=0.989 and M near perihelion, the derivative 1-e·cos(E) ≈ 0.011
		// causes Newton-Raphson to overshoot. This is why orbitalElementsToEllipse
		// computes positions directly from E instead of going through M → solveKepler → E.
		const e = MRKOS.e;
		let failures = 0;

		for (let j = 0; j <= 512; j++) {
			const E_orig = (j / 512) * 2 * Math.PI;
			const M = E_orig - e * Math.sin(E_orig);
			const E_recovered = solveKepler(M, e);

			const normalize = (x: number) => ((x % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
			const diff = Math.abs(normalize(E_recovered) - normalize(E_orig));
			const err = Math.min(diff, 2 * Math.PI - diff);
			if (err > 0.001) failures++;
		}
		// Newton-Raphson diverges for ~3% of E values at this eccentricity
		expect(failures).toBeGreaterThan(0);
		expect(failures).toBeLessThan(30);
	});
});

describe('orbitalElementsToCurve', () => {
	it('returns closed curve for Earth', () => {
		const { isOpen } = orbitalElementsToCurve(EARTH, 64);
		expect(isOpen).toBe(false);
	});

	it('returns closed curve for Mrkos (e=0.989, elliptic)', () => {
		const { isOpen, points } = orbitalElementsToCurve(MRKOS, 128);
		expect(isOpen).toBe(false);
		expect(points.length).toBeGreaterThan(0);
	});

	it('returns open curve for parabolic orbit', () => {
		const { isOpen } = orbitalElementsToCurve(PARABOLIC, 64);
		expect(isOpen).toBe(true);
	});

	it('returns open curve for hyperbolic orbit', () => {
		const { isOpen } = orbitalElementsToCurve(HYPERBOLIC, 64);
		expect(isOpen).toBe(true);
	});

	it('returns open curve for near-parabolic e=0.999', () => {
		const nearParabolic: OrbitalElements = {
			...MRKOS,
			e: 0.999,
			a: 500 // very large a for near-parabolic
		};
		const { isOpen } = orbitalElementsToCurve(nearParabolic, 64);
		expect(isOpen).toBe(true); // within 0.01 of 1
	});

	it('returns closed curve for e=0.98 (outside near-parabolic range)', () => {
		const el: OrbitalElements = { ...MRKOS, e: 0.98 };
		const { isOpen } = orbitalElementsToCurve(el, 64);
		expect(isOpen).toBe(false);
	});
});
