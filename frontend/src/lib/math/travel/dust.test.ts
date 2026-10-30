import { describe, expect, it } from 'vitest';
import { LIGHT_YEAR_KM } from '$lib/math/units';
import {
	DUST_MASS_KG_M3,
	grainMassKg,
	grainsAbove,
	largestGrainRadiusM,
	MEASURED_GRAIN_RADIUS_M
} from './dust';
import { INTERSTELLAR_N_H_CM3 } from './gas';

const MICRON_M = 1e-6;

/** The grains along a crossing over those at the Sun, where n_H is 0.25 cm⁻³. */
const GAS_SCALE = INTERSTELLAR_N_H_CM3 / 0.25;

/** The cumulative flux of Landgraf et al. 2000 as a density at 26 km/s, at the Sun. */
function landgrafAbove(radiusM: number): number {
	return (1e-6 / 26e3) * (grainMassKg(radiusM) / 1e-14) ** -1.1;
}

describe('the dust between the stars', () => {
	it('weighs a grain at 3 g/cm³', () => {
		expect(grainMassKg(MICRON_M) / ((4 / 3) * Math.PI * 1e-18 * 3000)).toBeCloseTo(1, 12);
	});

	it('scales the grains at the Sun by the density of the gas, 0.52', () => {
		expect(GAS_SCALE).toBeCloseTo(0.52, 12);
		// Ulysses above 1 µm, Krüger et al. 2015 Table 5 over 26 km/s.
		expect(grainsAbove(MICRON_M) / (GAS_SCALE * 3.06e-11)).toBeCloseTo(1, 2);
		expect(grainsAbove(0.01 * MICRON_M) / (GAS_SCALE * 7.2e-6)).toBeCloseTo(1, 2);
		// The mass of the grains at the Sun is 8.41e-24 kg/m³.
		expect(DUST_MASS_KG_M3 / (GAS_SCALE * 8.41e-24)).toBeCloseTo(1, 2);
	});

	it('sums the bins from the top down', () => {
		expect(grainsAbove(3 * MICRON_M) / (GAS_SCALE * landgrafAbove(3 * MICRON_M))).toBeCloseTo(
			1,
			12
		);
	});

	it('follows the slope of −1.1 in mass above the measured sizes', () => {
		expect(MEASURED_GRAIN_RADIUS_M).toBe(3 * MICRON_M);
		for (const um of [5, 70, 1000]) {
			const atSun = landgrafAbove(um * MICRON_M);
			expect(grainsAbove(um * MICRON_M) / (GAS_SCALE * atSun)).toBeCloseTo(1, 9);
		}
	});

	it('falls without a step across the edge of a bin', () => {
		for (const um of [0.03, 0.1, 0.3, 1, 3]) {
			const edge = um * MICRON_M;
			expect(grainsAbove(edge * (1 - 1e-9)) / grainsAbove(edge * (1 + 1e-9))).toBeCloseTo(1, 6);
		}
	});

	it('expects one grain of about 57 µm or more per m² on the way to Proxima', () => {
		const distanceKm = 4.2465 * LIGHT_YEAR_KM;
		const radiusM = largestGrainRadiusM(distanceKm);
		expect(grainsAbove(radiusM) * distanceKm * 1000).toBeCloseTo(1, 9);
		expect(radiusM / MICRON_M).toBeGreaterThan(52);
		expect(radiusM / MICRON_M).toBeLessThan(62);
	});

	it('finds a grain in the measured sizes over a short crossing', () => {
		const distanceKm = 1e-4 * LIGHT_YEAR_KM;
		const radiusM = largestGrainRadiusM(distanceKm);
		expect(radiusM).toBeLessThan(MEASURED_GRAIN_RADIUS_M);
		expect(grainsAbove(radiusM) * distanceKm * 1000).toBeCloseTo(1, 9);
	});

	it('holds about 2% of the mass of the gas', () => {
		// WD01 gives 1.1% and Ulysses 2.8% (Krüger et al. 2015).
		const gasKgM3 = INTERSTELLAR_N_H_CM3 * 1e6 * 1.6735e-27;
		expect(DUST_MASS_KG_M3 / gasKgM3).toBeGreaterThan(0.011);
		expect(DUST_MASS_KG_M3 / gasKgM3).toBeLessThan(0.028);
	});
});
