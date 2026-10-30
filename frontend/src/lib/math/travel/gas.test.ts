import { describe, expect, it } from 'vitest';
import { SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { G0_M_S2, SEC_PER_DAY } from './constants';
import {
	GAS_DOSE,
	gasKineticMeV,
	hullDoseFromRest,
	hullDosePerProton,
	INTERSTELLAR_N_H_CM3
} from './gas';

/** T (MeV), h_hull (pSv cm²), and the research's own H_cum (pSv cm² MeV), from section D. */
const TABLE: readonly (readonly [number, number, number])[] = [
	[5.8, 0, 0],
	[7, 0.048, 0.048],
	[10, 0.099, 0.264],
	[15, 0.3, 1.2],
	[20, 0.67, 3.54],
	[30, 2.08, 16.4],
	[50, 7.9, 106],
	[70, 20.6, 379],
	[100, 104, 1477],
	[102, 416, 1874],
	[110, 774, 6896],
	[120, 1020, 1.56e4],
	[150, 1590, 5.72e4],
	[200, 1410, 1.33e5],
	[300, 906, 2.43e5],
	[500, 838, 4.12e5],
	[1000, 1160, 8.77e5],
	[2000, 1230, 2.08e6],
	[5000, 1430, 6.1e6],
	[10000, 1490, 1.34e7]
];

const rapidityOf = (beta: number) => Math.atanh(beta);

/** Gas dose of a burn from rest to `beta` at 1 g, Sv. */
function oneGBurnSv(beta: number): number {
	return ((SPEED_OF_LIGHT_KM_S * 1000) / G0_M_S2) * GAS_DOSE.fromRest(rapidityOf(beta));
}

describe('the interstellar gas behind the hull', () => {
	it('uses 0.13 hydrogen nuclei per cm³ and 1.4 nucleons per hydrogen nucleus', () => {
		expect(INTERSTELLAR_N_H_CM3).toBe(0.13);
		const phi = rapidityOf(0.95);
		const perProton = hullDosePerProton(gasKineticMeV(phi));
		const beam = SPEED_OF_LIGHT_KM_S * 1e5 * Math.sinh(phi) * perProton * 1e-12;
		expect(GAS_DOSE.at(phi) / beam).toBeCloseTo(1.4 * 0.13, 12);
	});

	it('gives the kinetic energy per nucleon of the beam', () => {
		expect(gasKineticMeV(Math.acosh(3.2))).toBeCloseTo(2.2 * 938.272, 9);
		// Classical at 50 km/s: ½ m v².
		const beta = 50 / SPEED_OF_LIGHT_KM_S;
		expect(gasKineticMeV(rapidityOf(beta)) / (0.5 * 938.272 * beta ** 2)).toBeCloseTo(1, 6);
	});

	it('passes through the points of the dose table', () => {
		for (const [t, dose] of TABLE) expect(hullDosePerProton(t)).toBeCloseTo(dose, 9);
	});

	it('is zero below the threshold, linear to the first point and log-log after it', () => {
		for (const at of [hullDosePerProton, hullDoseFromRest]) {
			expect(at(1)).toBe(0);
			expect(at(5.8)).toBe(0);
		}
		expect(hullDosePerProton(6.4)).toBeCloseTo(0.024, 12);
		expect(hullDoseFromRest(6.4)).toBeCloseTo((0.024 * 0.6) / 2, 12);
		for (let i = 1; i + 1 < TABLE.length; i++) {
			const [lowT, lowDose] = TABLE[i];
			const [highT, highDose] = TABLE[i + 1];
			const middle = Math.sqrt(lowT * highT);
			expect(hullDosePerProton(middle) / Math.sqrt(lowDose * highDose)).toBeCloseTo(1, 9);
		}
		// Past the last point the last slope continues.
		expect(hullDosePerProton(20000) / ((1490 * 1490) / 1430)).toBeCloseTo(1, 9);
	});

	it('integrates the dose table exactly', () => {
		const steps = 200_000;
		const top = 20_000;
		let sum = 0;
		let previous = 0;
		for (let i = 1; i <= steps; i++) {
			// Steps even in log T, from just under the threshold.
			const t = 5.8 * (top / 5.8) ** (i / steps);
			const tPrevious = 5.8 * (top / 5.8) ** ((i - 1) / steps);
			const dose = hullDosePerProton(t);
			sum += ((dose + previous) / 2) * (t - tPrevious);
			previous = dose;
			if (i % 20_000 === 0) expect(sum / hullDoseFromRest(t)).toBeCloseTo(1, 4);
		}
	});

	it("stays near the research's own integral where the table is dense", () => {
		// The research integrated a finer curve. Near 7 MeV and across the jump at
		// 100 MeV its points differ more, but there the model is good to a factor of 3.
		for (const [t, , fromRest] of TABLE) {
			if (t < 15 || (t >= 100 && t <= 102)) continue;
			expect(Math.abs(hullDoseFromRest(t) / fromRest - 1)).toBeLessThan(0.05);
		}
	});

	it('gives the rates behind the hull of the research, per ship day', () => {
		// The research has two figures from the full model. This table holds fewer points.
		const research = [
			[0.2, 59],
			[0.3, 880],
			[0.5, 4.2e5],
			[0.7, 3.9e5],
			[0.9, 1.2e6],
			[0.95, 1.8e6],
			[0.99, 4.8e6],
			[0.995, 6.9e6]
		];
		for (const [beta, svPerDay] of research) {
			const ratio = (GAS_DOSE.at(rapidityOf(beta)) * SEC_PER_DAY) / svPerDay;
			expect(Math.abs(ratio - 1)).toBeLessThan(0.1);
		}
		expect(GAS_DOSE.at(rapidityOf(0.05))).toBe(0);
		expect(GAS_DOSE.at(rapidityOf(0.1))).toBe(0);
	});

	it('gives a 1 g burn to 0.12, 0.13 and 0.15 c the doses of the research', () => {
		// The research brackets each burn between two shapes of the neutron yield
		// at the threshold. The tables have two or three figures, so the top gets 3%.
		const research = [
			{ beta: 0.12, low: 0.359, high: 7.18 },
			{ beta: 0.13, low: 3.66, high: 18.8 },
			{ beta: 0.15, low: 38.8, high: 61.2 }
		];
		for (const { beta, low, high } of research) {
			expect(oneGBurnSv(beta)).toBeGreaterThan(low);
			expect(oneGBurnSv(beta)).toBeLessThan(high * 1.03);
		}
		expect(oneGBurnSv(0.11)).toBe(0);
	});

	it('sums the rate over a burn to the closed form', () => {
		for (const gamma of [1.155, 1.731, 3.194, 10.21]) {
			const phi = Math.acosh(gamma);
			const steps = 20_000;
			let sum = 0;
			for (let i = 0; i < steps; i++) {
				sum += (GAS_DOSE.at((phi * i) / steps) + GAS_DOSE.at((phi * (i + 1)) / steps)) / 2;
			}
			const ratio = (sum * phi) / steps / GAS_DOSE.fromRest(phi);
			expect(Math.abs(ratio - 1)).toBeLessThan(1e-4);
		}
	});
});
