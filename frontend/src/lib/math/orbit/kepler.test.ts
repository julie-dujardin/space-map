import { describe, it, expect, vi } from 'vitest';
import type { OrbitalElements } from '$lib/types/objects';
import { solveKepler, solveKeplerHyperbolic, solveBarker } from './solvers';
import { orbitalElementsToPosition } from './position';
import {
	orbitalElementsToEllipse,
	orbitalElementsToParabola,
	orbitalElementsToHyperbola,
	orbitalElementsToCurve
} from './orbit-curves';
import fixtures from './kepler.fixtures.json';

// Mock dateToJD so we don't depend on paraglide / real dates
vi.mock('$lib/format/date', () => ({
	dateToJD: (d: Date) => d.getTime() / 86400000 + 2440587.5
}));

const AU_SCALE = 10;

// ── Helpers ────────────────────────────────────────────────────────

function toElements(f: (typeof fixtures)[keyof typeof fixtures]): OrbitalElements {
	return { a: f.a, e: f.e, i: f.i, om: f.om, w: f.w, ma: f.ma, n: f.n, epoch: f.epoch };
}

function sceneDistances(pts: [number, number, number][]): number[] {
	return pts.map((p) => Math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) / AU_SCALE);
}

function maxGapRatio(pts: [number, number, number][]): number {
	const gaps: number[] = [];
	for (let i = 1; i < pts.length; i++) {
		gaps.push(
			Math.sqrt(
				(pts[i][0] - pts[i - 1][0]) ** 2 +
					(pts[i][1] - pts[i - 1][1]) ** 2 +
					(pts[i][2] - pts[i - 1][2]) ** 2
			)
		);
	}
	const mean = gaps.reduce((a, b) => a + b, 0) / gaps.length;
	return Math.max(...gaps) / mean;
}

/** A synthetic parabolic orbit (e=1, q-based). */
const SYNTHETIC_PARABOLIC: OrbitalElements = {
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

// ── Fixture objects ────────────────────────────────────────────────

const EMB = toElements(fixtures.earthMoonBarycenter);
const CERES = toElements(fixtures.ceres);
const CHIRON = toElements(fixtures.chiron);
const ERIS = toElements(fixtures.eris);
const HALLEY = toElements(fixtures.halley);
const MRKOS = toElements(fixtures.mrkos);
const A2020H9 = toElements(fixtures.a2020h9);
const CATALINA_HYP = toElements(fixtures.catalinaHyperbolic);
const NEAR_CIRC = toElements(fixtures.nearCircularAsteroid);
const PHOBOS = toElements(fixtures.phobos);

// All elliptic orbits from fixtures (e < 1, used for batch tests)
const ELLIPTIC_ORBITS = [
	{ name: 'Earth-Moon Barycenter', el: EMB },
	{ name: 'Ceres', el: CERES },
	{ name: 'Chiron', el: CHIRON },
	{ name: 'Eris', el: ERIS },
	{ name: 'Halley', el: HALLEY },
	{ name: 'Mrkos', el: MRKOS },
	{ name: '2015 KK487', el: NEAR_CIRC },
	{ name: 'Phobos', el: PHOBOS }
];

// ── Kepler solvers ─────────────────────────────────────────────────

describe('solveKepler', () => {
	it('returns M for circular orbit (e=0)', () => {
		const E = solveKepler(1.0, 0);
		expect(E).toBeCloseTo(1.0, 10);
	});

	it('solves known case e=0.5, M=1', () => {
		const E = solveKepler(1.0, 0.5);
		expect(E - 0.5 * Math.sin(E)).toBeCloseTo(1.0, 10);
	});

	it.each([
		{ name: 'near-circular', e: NEAR_CIRC.e },
		{ name: 'Ceres', e: CERES.e },
		{ name: 'Chiron', e: CHIRON.e },
		{ name: 'Eris', e: ERIS.e },
		{ name: 'Halley', e: HALLEY.e },
		{ name: 'Mrkos', e: MRKOS.e }
	])('round-trips M for $name (e=$e)', ({ e }) => {
		// Sample several M values
		for (const M of [0.01, 0.5, 1.0, 3.0, 5.0]) {
			const E = solveKepler(M, e);
			expect(E - e * Math.sin(E)).toBeCloseTo(M, 8);
		}
	});
});

describe('solveKeplerHyperbolic', () => {
	it('solves e=1.5 M=1', () => {
		const H = solveKeplerHyperbolic(1.0, 1.5);
		expect(1.5 * Math.sinh(H) - H).toBeCloseTo(1.0, 8);
	});

	it('solves for Catalina hyperbolic orbit', () => {
		const M = 0.1;
		const H = solveKeplerHyperbolic(M, CATALINA_HYP.e);
		expect(CATALINA_HYP.e * Math.sinh(H) - H).toBeCloseTo(M, 8);
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

// ── Ellipse curve generator ────────────────────────────────────────

describe('orbitalElementsToEllipse', () => {
	it.each(ELLIPTIC_ORBITS)('all points finite and loop closes for $name', ({ el }) => {
		const pts = orbitalElementsToEllipse(el, 128);
		expect(pts.length).toBe(129);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
		// First and last point should coincide (closed loop)
		const first = pts[0];
		const last = pts[pts.length - 1];
		expect(first[0]).toBeCloseTo(last[0], 3);
		expect(first[1]).toBeCloseTo(last[1], 3);
		expect(first[2]).toBeCloseTo(last[2], 3);
	});

	it.each(ELLIPTIC_ORBITS)('perihelion and aphelion distances match for $name', ({ el }) => {
		const pts = orbitalElementsToEllipse(el, 512);
		const distances = sceneDistances(pts);
		const expectedQ = el.a * (1 - el.e);
		const expectedQQ = el.a * (1 + el.e);
		expect(Math.min(...distances)).toBeCloseTo(expectedQ, 1);
		expect(Math.max(...distances)).toBeCloseTo(expectedQQ, 0);
	});

	it.each(ELLIPTIC_ORBITS)('no large gaps for $name', ({ el }) => {
		const pts = orbitalElementsToEllipse(el, 512);
		// E-uniform sampling keeps max/mean gap ratio reasonable
		expect(maxGapRatio(pts)).toBeLessThan(5);
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

// ── Parabola curve generator ───────────────────────────────────────

describe('orbitalElementsToParabola', () => {
	it('generates finite points for synthetic parabolic orbit', () => {
		const pts = orbitalElementsToParabola(SYNTHETIC_PARABOLIC, 64);
		expect(pts.length).toBe(65);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
	});

	it('minimum distance is close to q for synthetic orbit', () => {
		const pts = orbitalElementsToParabola(SYNTHETIC_PARABOLIC, 512);
		const minDist = Math.min(...sceneDistances(pts));
		expect(minDist).toBeCloseTo(SYNTHETIC_PARABOLIC.q!, 1);
	});

	it('generates finite points for near-parabolic A/2020 H9', () => {
		const q = A2020H9.a * (1 - A2020H9.e);
		const pts = orbitalElementsToParabola({ ...A2020H9, q }, 512);
		expect(pts.length).toBeGreaterThan(0);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
		const minDist = Math.min(...sceneDistances(pts));
		expect(minDist).toBeCloseTo(q, 1);
	});
});

// ── Hyperbola curve generator ──────────────────────────────────────

describe('orbitalElementsToHyperbola', () => {
	it('generates finite points for Catalina', () => {
		const pts = orbitalElementsToHyperbola(CATALINA_HYP, 64);
		expect(pts.length).toBeGreaterThan(0);
		for (const p of pts) {
			expect(p.every(isFinite)).toBe(true);
		}
	});
});

// ── Curve dispatcher ───────────────────────────────────────────────

describe('orbitalElementsToCurve', () => {
	it.each([
		{ name: 'EMB (e=0.022)', el: EMB },
		{ name: 'Ceres (e=0.081)', el: CERES },
		{ name: 'Chiron (e=0.379)', el: CHIRON },
		{ name: 'Eris (e=0.438)', el: ERIS },
		{ name: 'Halley (e=0.968)', el: HALLEY },
		{ name: 'Mrkos (e=0.989)', el: MRKOS }
	])('returns closed curve for $name', ({ el }) => {
		const { isOpen, points } = orbitalElementsToCurve(el, 128);
		expect(isOpen).toBe(false);
		expect(points.length).toBeGreaterThan(0);
	});

	it('returns open curve for near-parabolic A/2020 H9 (e=0.992)', () => {
		const { isOpen } = orbitalElementsToCurve(A2020H9, 64);
		expect(isOpen).toBe(true);
	});

	it('returns open curve for synthetic parabolic orbit', () => {
		const { isOpen } = orbitalElementsToCurve(SYNTHETIC_PARABOLIC, 64);
		expect(isOpen).toBe(true);
	});

	it('returns open curve for Catalina (hyperbolic)', () => {
		const { isOpen } = orbitalElementsToCurve(CATALINA_HYP, 64);
		expect(isOpen).toBe(true);
	});
});
