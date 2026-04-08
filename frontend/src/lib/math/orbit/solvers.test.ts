import { describe, it, expect } from 'vitest';
import { solveKepler, solveKeplerHyperbolic, solveBarker } from './solvers';
import { NEAR_CIRC, CERES, CHIRON, ERIS, HALLEY, MRKOS, CATALINA_HYP } from './test-helpers';

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
		for (const M of [0.01, 0.5, 1.0, 3.0, 5.0]) {
			const E = solveKepler(M, e);
			expect(E - e * Math.sin(E)).toBeCloseTo(M, 8);
		}
	});

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
