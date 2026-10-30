import { describe, expect, it } from 'vitest';
import { INTERSTELLAR_N_H_CM3 } from './gas';
import { INTERSTELLAR_DOSE_SV_PER_DAY } from './radiation';
import { CONCRETE_CAP_M, ISS_DOSE_SV_PER_DAY, radiationShield } from './shield';

describe('the radiation shield of a crossing', () => {
	it('was computed for the gas density and the cosmic ray rate in force', () => {
		expect(INTERSTELLAR_N_H_CM3).toBe(0.13);
		expect(INTERSTELLAR_DOSE_SV_PER_DAY).toBeCloseTo(4.873e-3, 5);
		expect(ISS_DOSE_SV_PER_DAY).toBe(0.6e-3);
	});

	it('gives the sides 303 g/cm² of water at every speed', () => {
		for (const t of [0, 1, 100, 10000]) {
			expect(radiationShield(t).sideIceM).toBeCloseTo(303 / 0.917 / 100, 6);
		}
	});

	it('gives a craft at rest the same front as sides, and no step up to the table', () => {
		const rest = radiationShield(0);
		expect(rest.frontIceM).toBe(rest.sideIceM);
		const below = radiationShield(0.1 - 1e-9);
		const first = radiationShield(0.1);
		expect(below.frontIceM).toBeCloseTo(first.frontIceM, 6);
		expect(below.frontIronM).toBeCloseTo(first.frontIronM, 6);
	});

	it('gives the fronts of the research', () => {
		// T, ice m, iron m (section 4).
		const research: readonly (readonly [number, number, number])[] = [
			[145, 9.19, 1.95],
			[400, 19.97, 3.8],
			[2000, 29.78, 5.14],
			[10000, 31.75, 5.48]
		];
		for (const [t, ice, iron] of research) {
			const shield = radiationShield(t);
			expect(shield.frontIceM).toBeCloseTo(ice, 1);
			expect(shield.frontIronM).toBeCloseTo(iron, 1);
		}
		expect(CONCRETE_CAP_M).toBe(0.6);
	});

	it('makes the front more than a third thicker than the sides from about 0.28 c', () => {
		// 39 MeV per nucleon is 0.28 c.
		const ratio = (t: number) => radiationShield(t).frontIceM / radiationShield(t).sideIceM;
		expect(ratio(35)).toBeLessThan(1.33);
		expect(ratio(45)).toBeGreaterThan(1.33);
	});

	it('never makes the front thinner than the sides, and grows with the speed', () => {
		let last = 0;
		for (const t of [0, 0.1, 1, 10, 45, 100, 400, 2000, 30000, 1e6]) {
			const { frontIceM, sideIceM } = radiationShield(t);
			expect(frontIceM).toBeGreaterThanOrEqual(sideIceM);
			expect(frontIceM).toBeGreaterThanOrEqual(last);
			last = frontIceM;
		}
	});
});
