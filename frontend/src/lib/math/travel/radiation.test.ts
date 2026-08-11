import { describe, expect, it } from 'vitest';
import {
	BELT_MODEL_UNCERTAINTY_FACTOR,
	BELT_SHIELDING_FLOOR,
	CANCER_RISK_PER_SV,
	LETHAL_DOSE_GY,
	cancerRiskFraction,
	lethalDoseFraction,
	beltPassDoseGy,
	beltShieldingFactor,
	decimalYearOf,
	gcrDoseRateSvPerDay,
	jovianBeltRateGyPerDay,
	openSkyFraction,
	radialFactor,
	solarCycleFactor
} from './radiation';

/**
 * Jupiter, and the two spacecraft that have flown through its belts and had
 * the dose worked out for a body rather than for electronics.
 *
 * These are the same figures `constants/radiation/belt_field.py` is tested
 * against. That is the point of them being here as well: the model is fitted
 * and validated on the Python side and mirrored into this file by hand, so
 * these numbers are what would catch the mirror drifting out of step.
 */
const JUPITER_RADIUS_KM = 71492;
const JUPITER_MU = 1.26686534e8;
const PIONEER_SHIELDING_G_CM2 = 0.3 * 2.7;
const PIONEER_V_INFINITY_KMS = 9.5;

const pioneerPass = (altitudeKm: number) =>
	beltPassDoseGy(
		altitudeKm + JUPITER_RADIUS_KM,
		PIONEER_V_INFINITY_KMS,
		PIONEER_SHIELDING_G_CM2,
		JUPITER_RADIUS_KM,
		JUPITER_MU
	);

describe('solar cycle', () => {
	it('peaks at solar minimum rather than at maximum', () => {
		const minimum = solarCycleFactor(2019.96);
		const maximum = solarCycleFactor(2019.96 + 5.5);
		expect(minimum).toBeGreaterThan(maximum);
	});

	it('averages to one across a cycle, so the reference is a cycle mean', () => {
		const quarter = solarCycleFactor(2019.96 + 11 / 4);
		expect(quarter).toBeCloseTo(1, 6);
	});

	it('swings by the ratio Guo measured over a whole cycle', () => {
		const swing = solarCycleFactor(2019.96) / solarCycleFactor(2019.96 + 5.5);
		expect(swing).toBeCloseTo(1.59 / 0.65, 3);
	});
});

describe('cosmic rays in free space', () => {
	it('reproduces what RAD read in cruise', () => {
		// 1.58 mSv/day at a mean 1.25 au during 2012 — the measurement the
		// reference dose was fitted to.
		const jd = 2455927.5 + 0.1 * 365.25;
		expect(gcrDoseRateSvPerDay(jd, 1.25)).toBeCloseTo(1.58e-3, 4);
	});

	it('gets worse further out', () => {
		expect(radialFactor(5.2)).toBeGreaterThan(radialFactor(1));
		expect(radialFactor(1)).toBe(1);
	});

	it('puts J2000 at the year 2000', () => {
		expect(decimalYearOf(2451545)).toBeCloseTo(2000, 6);
	});
});

describe('open sky', () => {
	it('is half on any surface, whatever the body', () => {
		expect(openSkyFraction(1737.4, 1737.4)).toBe(0.5);
		expect(openSkyFraction(6371, 6371)).toBe(0.5);
	});

	it('approaches the whole sky far away', () => {
		expect(openSkyFraction(6371, 1e9)).toBeCloseTo(1, 6);
	});

	it('never reports more sky than there is', () => {
		for (const d of [1, 1000, 6371, 7000, 1e6]) {
			const open = openSkyFraction(6371, d);
			expect(open).toBeGreaterThanOrEqual(0.5);
			expect(open).toBeLessThanOrEqual(1);
		}
	});
});

describe('belt shielding', () => {
	it('reproduces the two decades the source figure spans', () => {
		expect(beltShieldingFactor(0.11)).toBe(1);
		expect(beltShieldingFactor(2.7)).toBeCloseTo(0.01, 3);
	});

	it('floors rather than extrapolating to a vault', () => {
		// The bare exponential returns 1e-11 here, which would read as a Jupiter
		// pass being survivable behind a thick enough wall.
		expect(beltShieldingFactor(20)).toBe(BELT_SHIELDING_FLOOR);
	});
});

describe('the Jovian belt profile', () => {
	it('is flat inside the peak and falls away outside it', () => {
		expect(jovianBeltRateGyPerDay(1.5)).toBe(jovianBeltRateGyPerDay(3));
		expect(jovianBeltRateGyPerDay(5)).toBeLessThan(jovianBeltRateGyPerDay(3));
		expect(jovianBeltRateGyPerDay(26.3)).toBeLessThan(jovianBeltRateGyPerDay(9.4));
	});

	it('keeps Callisto where Johnson puts it against Europa', () => {
		expect(jovianBeltRateGyPerDay(9.4) / jovianBeltRateGyPerDay(26.3)).toBeCloseTo(250, 0);
	});
});

describe('a pass through Jupiter', () => {
	it('reproduces what Pioneer 10 took', () => {
		expect(pioneerPass(130354)).toBeCloseTo(4500, -2);
	});

	it('over-predicts Pioneer 11 by the amount it is known to', () => {
		// Never fitted to, and a polar pass, which this model treats as
		// equatorial. Pinned so a change that deepens the bias fails.
		const ratio = pioneerPass(42760) / 1200;
		expect(ratio).toBeGreaterThan(3);
		expect(ratio).toBeLessThan(5);
	});

	it('makes speed the thing that buys a pass down', () => {
		const slow = beltPassDoseGy(3 * JUPITER_RADIUS_KM, 5, 0.11, JUPITER_RADIUS_KM, JUPITER_MU);
		const fast = beltPassDoseGy(3 * JUPITER_RADIUS_KM, 20, 0.11, JUPITER_RADIUS_KM, JUPITER_MU);
		expect(fast).toBeLessThan(slow);
	});

	it('costs nothing when there is no pass', () => {
		expect(beltPassDoseGy(0, 9.5, 0.11, JUPITER_RADIUS_KM, JUPITER_MU)).toBe(0);
		expect(beltPassDoseGy(3 * JUPITER_RADIUS_KM, 0, 0.11, JUPITER_RADIUS_KM, JUPITER_MU)).toBe(0);
	});

	it('is lethal by orders of magnitude behind a crewed hull', () => {
		// The finding the anchors were published for. 4 Gy is roughly half of
		// unaided survival; this is the number the planner exists to surface.
		expect(
			beltPassDoseGy(2 * JUPITER_RADIUS_KM, 9.5, 10, JUPITER_RADIUS_KM, JUPITER_MU)
		).toBeGreaterThan(4);
	});
});

describe('what it does to a person', () => {
	it('puts one lethal dose at the untreated LD50', () => {
		expect(lethalDoseFraction(LETHAL_DOSE_GY)).toBe(1);
		expect(LETHAL_DOSE_GY).toBeGreaterThanOrEqual(4);
		expect(LETHAL_DOSE_GY).toBeLessThanOrEqual(6);
	});

	it('reads the Pioneer passes as hundreds of lethal doses', () => {
		// Miller's conclusion was that even the gentler of the two would have
		// killed a crew. Anything under 1 here would contradict the source.
		expect(lethalDoseFraction(1200)).toBeGreaterThan(100);
		expect(lethalDoseFraction(4500)).toBeGreaterThan(100);
	});

	it('brackets a belt pass by the factor the model is known to', () => {
		const central = lethalDoseFraction(3.4);
		expect(central / BELT_MODEL_UNCERTAINTY_FACTOR).toBeLessThan(central);
		expect(central * BELT_MODEL_UNCERTAINTY_FACTOR).toBeGreaterThan(central);
		// Near LD50 the band spans survivable to certainly fatal, which is the
		// honest state of the model rather than a defect in the display.
		expect(central / BELT_MODEL_UNCERTAINTY_FACTOR).toBeLessThan(1);
		expect(central * BELT_MODEL_UNCERTAINTY_FACTOR).toBeGreaterThan(1);
	});

	it('scales cancer risk linearly off the ICRP coefficient', () => {
		expect(cancerRiskFraction(1)).toBeCloseTo(CANCER_RISK_PER_SV, 10);
		expect(cancerRiskFraction(0)).toBe(0);
		// A Mars round trip near solar minimum, 1.59 Sv: a few percent.
		expect(cancerRiskFraction(1.59)).toBeGreaterThan(0.05);
		expect(cancerRiskFraction(1.59)).toBeLessThan(0.08);
	});

	it('keeps the two quantities on separate scales', () => {
		// 1 Sv of cruise is a few percent of lifetime risk; 1 Gy of belt is a
		// fifth of a lethal dose. Anything that made these interchangeable would
		// be the mistake the two units exist to prevent.
		expect(cancerRiskFraction(1)).toBeLessThan(0.1);
		expect(lethalDoseFraction(1)).toBeGreaterThan(0.2);
	});
});
