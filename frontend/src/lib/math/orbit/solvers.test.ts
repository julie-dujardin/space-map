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

	it('round-trips E→M→solveKepler→E for all E at high eccentricity', () => {
		// At e≈0.989 the derivative 1-e·cos(E) collapses near perihelion. Unclamped
		// Newton-Raphson oscillates; the damped step in solveKepler keeps it convergent
		// so the body position stays pinned to the rendered ellipse every frame.
		const e = MRKOS.e;
		for (let j = 0; j <= 512; j++) {
			const E_orig = (j / 512) * 2 * Math.PI;
			const M = E_orig - e * Math.sin(E_orig);
			const E_recovered = solveKepler(M, e);

			const normalize = (x: number) => ((x % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
			const diff = Math.abs(normalize(E_recovered) - normalize(E_orig));
			const err = Math.min(diff, 2 * Math.PI - diff);
			expect(err).toBeLessThan(1e-6);
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

	it('converges for a near-parabolic orbit at small M', () => {
		// C/1962 C1 (Seki-Lines) propagated to 2026: e−1 ≈ 4e-6 flattens f'(0),
		// which used to send Newton past H = 100 and leave it near 90 — a point
		// ~1e40 AU out that overflowed the Float32 vertex buffer.
		const e = 1.0000044604121461;
		const M = 6.8e-4;
		const H = solveKeplerHyperbolic(M, e);
		expect(e * Math.sinh(H) - H).toBeCloseTo(M, 10);
		expect(H).toBeLessThan(1);
	});

	it('round-trips M across eccentricities and magnitudes', () => {
		for (const e of [1.0000001, 1.001, 1.1, 1.5, 3, 10]) {
			for (const M of [-50, -1, -1e-6, 1e-6, 0.01, 1, 50, 1e4]) {
				const H = solveKeplerHyperbolic(M, e);
				expect(isFinite(H)).toBe(true);
				// Relative: at M = 1e4 an absolute tolerance sits below f64 resolution.
				expect((e * Math.sinh(H) - H) / M).toBeCloseTo(1, 9);
			}
		}
	});

	it('returns NaN when the root is past the sinh overflow limit', () => {
		expect(solveKeplerHyperbolic(Number.MAX_VALUE, 1.5)).toBeNaN();
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
