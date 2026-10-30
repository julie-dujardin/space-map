import { describe, expect, it } from 'vitest';
import {
	BELT_MODEL_UNCERTAINTY_FACTOR,
	BELT_SHIELDING_FLOOR,
	CANCER_RISK_PER_SV,
	LETHAL_DOSE_GY,
	cancerRiskFraction,
	lethalDoseFraction,
	beltPassDoseGy,
	beltAttenuation,
	beltRateGyPerDay,
	beltShieldingFactor,
	JPL_SHELL_G_CM2,
	type BeltProfile,
	BELT_PROFILES,
	cosmicRayBoost,
	cosmicRayBoostFromRest,
	decimalYearOf,
	gcrDoseRateSvPerDay,
	HELIOPAUSE_AU,
	INTERSTELLAR_DOSE_SV_PER_DAY,
	interstellarDoseRateSvPerDay,
	jovianBeltRateGyPerDay,
	openSkyFraction,
	radialFactor,
	solarCycleFactor
} from './radiation';
import { DAYS_PER_YEAR, J2000_JD } from '$lib/time/jd';

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
const JUPITER = BELT_PROFILES['naif-599'];
const JUPITER_MU = 1.26686534e8;
const PIONEER_SHIELDING_G_CM2 = 0.3 * 2.7;
const PIONEER_V_INFINITY_KMS = 9.5;

const pioneerPass = (altitudeKm: number) =>
	beltPassDoseGy(
		JUPITER,
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

describe('cosmic rays between the stars', () => {
	const minimumJd = J2000_JD + 19.96 * DAYS_PER_YEAR;

	it('holds 1.8 times the rate at 1 au at solar minimum past the heliopause', () => {
		expect(INTERSTELLAR_DOSE_SV_PER_DAY / gcrDoseRateSvPerDay(minimumJd, 1)).toBeCloseTo(1.8, 9);
		expect(INTERSTELLAR_DOSE_SV_PER_DAY).toBeCloseTo(4.87e-3, 5);
		// The Sun does not modulate the flux there.
		const maximumJd = minimumJd + 5.5 * DAYS_PER_YEAR;
		expect(interstellarDoseRateSvPerDay(maximumJd, HELIOPAUSE_AU)).toBe(
			INTERSTELLAR_DOSE_SV_PER_DAY
		);
	});

	it('holds the fit at the ends of its range inside the heliopause', () => {
		expect(interstellarDoseRateSvPerDay(minimumJd, 60)).toBe(gcrDoseRateSvPerDay(minimumJd, 9.5));
		expect(interstellarDoseRateSvPerDay(minimumJd, 0.3)).toBe(gcrDoseRateSvPerDay(minimumJd, 1));
	});
});

describe('the boost of the cosmic ray dose on a fast craft', () => {
	const TABLE: readonly (readonly [number, number])[] = [
		[1, 1],
		[1.02, 1.161],
		[1.048, 1.332],
		[1.1, 1.551],
		[1.155, 1.662],
		[1.25, 1.807],
		[1.4, 2.093],
		[1.667, 2.68],
		[2.0, 3.435],
		[2.294, 4.105],
		[3.2, 6.177],
		[5.0, 10.47],
		[7.089, 15.69],
		[10.0, 23.36],
		[15.0, 37.66],
		[22.4, 60.55],
		[30.0, 85.47]
	];
	const boostAt = (gamma: number) => cosmicRayBoost(Math.acosh(gamma));

	/** Rapidity at the end of a burn at `g` gravities over half of `ly`, flat out. */
	function halfwayRapidity(g: number, ly: number): number {
		const accel = g * 9.80665;
		const halfM = (ly * 9.4607304725808e15) / 2;
		return Math.acosh(1 + (accel * halfM) / 299_792_458 ** 2);
	}

	it('passes through the points of the table', () => {
		for (const [gamma, boost] of TABLE) expect(boostAt(gamma)).toBeCloseTo(boost, 9);
	});

	it('is linear in ln F against the rapidity between the points', () => {
		for (let i = 0; i + 1 < TABLE.length; i++) {
			const [lowGamma, lowBoost] = TABLE[i];
			const [highGamma, highBoost] = TABLE[i + 1];
			const middle = (Math.acosh(lowGamma) + Math.acosh(highGamma)) / 2;
			expect(cosmicRayBoost(middle)).toBeCloseTo(Math.sqrt(lowBoost * highBoost), 9);
		}
		// The peak of Nostalgia for Infinity, 1 g to Proxima.
		expect(boostAt(3.193627)).toBeCloseTo(6.1623, 4);
	});

	it('continues the last slope past γ = 30', () => {
		expect(boostAt(40)).toBeCloseTo(120.0, 3);
	});

	it('sums to the same total as a fine trapezoid of itself', () => {
		for (const phi of [1e-4, 0.1, 1.1456, 1.8288, 3.0144, 4.5]) {
			const steps = 20_000;
			let sum = 0;
			for (let i = 0; i < steps; i++) {
				sum += (cosmicRayBoost((phi * i) / steps) + cosmicRayBoost((phi * (i + 1)) / steps)) / 2;
			}
			expect(cosmicRayBoostFromRest(phi) / ((sum * phi) / steps)).toBeCloseTo(1, 7);
		}
	});

	it('agrees with the research over a burn of each reference trip', () => {
		// The research integrates a table of 60 points. This one has 17, so it is up to 0.3% higher.
		const cases = [
			{ g: 1, ly: 4.25, research: 4.901196 },
			{ g: 1.5, ly: 11.9, research: 20.414341 },
			{ g: 1 / 3, ly: 4.25, research: 1.97589 }
		];
		for (const { g, ly, research } of cases) {
			const ratio = cosmicRayBoostFromRest(halfwayRapidity(g, ly)) / research;
			expect(Math.abs(ratio - 1)).toBeLessThan(0.005);
		}
	});

	it('is about one at the heliopause on a 1 g burn, and at the speed of a coast', () => {
		// 120 au at 1 g is about 0.06 c.
		const heliopauseGamma = 1 + (9.80665 * 120 * 1.495978707e11) / 299_792_458 ** 2;
		expect(boostAt(heliopauseGamma)).toBeCloseTo(1.048, 3);
		expect(cosmicRayBoost(Math.atanh(50 / 299_792.458))).toBeCloseTo(1.0001, 4);
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
		expect(beltAttenuation(0.11)).toBe(1);
		expect(beltAttenuation(2.7)).toBeCloseTo(0.01, 3);
	});

	it('floors rather than extrapolating to a vault', () => {
		// The bare exponential returns 1e-11 here, which would read as a Jupiter
		// pass being survivable behind a thick enough wall.
		expect(beltAttenuation(20)).toBe(BELT_SHIELDING_FLOOR);
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
		const slow = beltPassDoseGy(
			JUPITER,
			3 * JUPITER_RADIUS_KM,
			5,
			0.11,
			JUPITER_RADIUS_KM,
			JUPITER_MU
		);
		const fast = beltPassDoseGy(
			JUPITER,
			3 * JUPITER_RADIUS_KM,
			20,
			0.11,
			JUPITER_RADIUS_KM,
			JUPITER_MU
		);
		expect(fast).toBeLessThan(slow);
	});

	it('costs nothing when there is no pass', () => {
		expect(beltPassDoseGy(JUPITER, 0, 9.5, 0.11, JUPITER_RADIUS_KM, JUPITER_MU)).toBe(0);
		expect(
			beltPassDoseGy(JUPITER, 3 * JUPITER_RADIUS_KM, 0, 0.11, JUPITER_RADIUS_KM, JUPITER_MU)
		).toBe(0);
	});

	it('is lethal by orders of magnitude behind a crewed hull', () => {
		// The finding the anchors were published for. 4 Gy is roughly half of
		// unaided survival; this is the number the planner exists to surface.
		expect(
			beltPassDoseGy(JUPITER, 2 * JUPITER_RADIUS_KM, 9.5, 10, JUPITER_RADIUS_KM, JUPITER_MU)
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

describe('the other belts', () => {
	/**
	 * Saturn's and Neptune's profiles are read off JPL's published curves, so
	 * these pin the reading rather than any physics — and, like the Jupiter
	 * numbers above, they are what catches the mirror drifting from
	 * `constants/radiation/belt_field.py`.
	 */
	const JUPITER_PROFILE = BELT_PROFILES['naif-599'];
	const SATURN = BELT_PROFILES['naif-699'];
	const NEPTUNE = BELT_PROFILES['naif-899'];

	const at = (profile: BeltProfile, lShell: number) =>
		beltRateGyPerDay(profile, lShell) * beltShieldingFactor(JPL_SHELL_G_CM2, profile.shieldingGCm2);

	it('passes through its own samples', () => {
		for (const profile of Object.values(BELT_PROFILES)) {
			for (const [lShell, rate] of profile.samples) {
				expect(beltRateGyPerDay(profile, lShell)).toBeCloseTo(rate, 10);
			}
		}
	});

	it('peaks Neptune at L = 7 and lets it fall away inside that', () => {
		// The one profile whose inner branch was measured. Held flat, as
		// Jupiter's is, a close pass would read a hundred times worse.
		expect(beltRateGyPerDay(NEPTUNE, 7)).toBeGreaterThan(beltRateGyPerDay(NEPTUNE, 9));
		expect(beltRateGyPerDay(NEPTUNE, 2.2)).toBeLessThan(beltRateGyPerDay(NEPTUNE, 7));
		expect(beltRateGyPerDay(NEPTUNE, 1.5)).toBeLessThan(beltRateGyPerDay(NEPTUNE, 2.2));
	});

	it('holds Saturn flat inside the innermost distance anyone drew', () => {
		expect(beltRateGyPerDay(SATURN, 1.5)).toBe(beltRateGyPerDay(SATURN, 2.55));
	});

	it('leaves both far gentler than Jupiter, and Neptune gentlest', () => {
		// At matched shielding, since the three are not quoted behind the same
		// aluminium — comparing them raw would flatter Saturn threefold.
		expect(at(JUPITER_PROFILE, 7)).toBeGreaterThan(100 * at(SATURN, 7));
		expect(at(SATURN, 7)).toBeGreaterThan(at(NEPTUNE, 7));
	});
});
