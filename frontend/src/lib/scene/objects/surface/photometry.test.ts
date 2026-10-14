import { describe, it, expect } from 'vitest';
import { lunarLambertGain, lunarLambertWeight } from './photometry';

/**
 * Contract tests for the CPU port of the GLSL `lunarLambertWeight` and
 * `lunarLambertGain`. The shader and these functions must agree on the values.
 */

/** The law as McEwen (1996) gives it, relative to ground that faces the Sun
 *  and the camera. */
function mcEwen(phaseDeg: number, mu0: number, mu: number): number {
	const weight = 1 - 0.019 * phaseDeg + 0.000242 * phaseDeg ** 2 - 0.00000146 * phaseDeg ** 3;
	return (2 * weight * mu0) / (mu0 + mu) + (1 - weight) * mu0;
}

describe('lunarLambertWeight', () => {
	it('is all lunar at phase 0', () => {
		expect(lunarLambertWeight(0)).toBe(1);
	});

	it('follows the polynomial of McEwen', () => {
		expect(lunarLambertWeight(30)).toBeCloseTo(0.60838, 5);
		expect(lunarLambertWeight(60)).toBeCloseTo(0.41584, 5);
		expect(lunarLambertWeight(90)).toBeCloseTo(0.18586, 5);
	});

	it('goes down as the phase angle goes up', () => {
		for (let phase = 1; phase <= 180; phase++) {
			expect(lunarLambertWeight(phase)).toBeLessThanOrEqual(lunarLambertWeight(phase - 1));
		}
	});

	it('is all Lambert where the polynomial is negative', () => {
		expect(lunarLambertWeight(103)).toBeGreaterThan(0);
		expect(lunarLambertWeight(105)).toBe(0);
		expect(lunarLambertWeight(180)).toBe(0);
	});
});

describe('lunarLambertGain', () => {
	it('does not change ground that faces the Sun and the camera', () => {
		for (const phase of [0, 30, 90, 150]) expect(lunarLambertGain(phase, 1, 1)).toBeCloseTo(1, 12);
	});

	it('makes the full disc flat', () => {
		// At phase 0 the two cosines are equal at each point of the disc.
		for (const mu of [1, 0.7, 0.312, 0.1, 0.03]) {
			expect(lunarLambertGain(0, mu, mu) * mu).toBeCloseTo(1, 12);
		}
	});

	it('agrees with the law of McEwen where the emission cosine is the larger one', () => {
		for (const [phase, mu0, mu] of [
			[20, 0.9, 0.95],
			[60, 0.5, 1],
			[60, 0.1, 0.8],
			[90, 0.2, 0.3]
		]) {
			expect(lunarLambertGain(phase, mu0, mu) * mu0).toBeCloseTo(mcEwen(phase, mu0, mu), 12);
		}
	});

	it('holds the lunar part where the camera sees the ground at a lower angle than the Sun', () => {
		expect(lunarLambertGain(60, 0.866, 0.02)).toBe(lunarLambertGain(60, 0.866, 0.866));
		expect(lunarLambertGain(10, 0.25, 0)).toBe(lunarLambertGain(10, 0.25, 0.25));
	});

	it('makes no ground brighter than ground that faces the Sun and the camera', () => {
		for (const phase of [0, 10, 30, 60, 90, 120]) {
			for (let mu0 = 0; mu0 <= 1; mu0 += 0.05) {
				for (let mu = -0.2; mu <= 1; mu += 0.05) {
					expect(lunarLambertGain(phase, mu0, mu) * mu0).toBeLessThanOrEqual(1 + 1e-12);
				}
			}
		}
	});

	it('is the Lambert law at a high phase angle', () => {
		expect(lunarLambertGain(120, 0.4, 0.1)).toBe(1);
		expect(lunarLambertGain(170, 0.05, 0)).toBe(1);
	});

	it('is bounded where the Sun and the camera are both at the horizon', () => {
		expect(lunarLambertGain(0, 0, 0)).toBeCloseTo(40, 9);
		expect(lunarLambertGain(0, -0.2, -0.2)).toBeCloseTo(40, 9);
		expect(lunarLambertGain(0, 1e-4, 0) * 1e-4).toBeLessThan(0.01);
	});
});
