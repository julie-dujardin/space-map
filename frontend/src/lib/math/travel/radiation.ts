/**
 * The dose of ionizing radiation on a trajectory. There are two models, because
 * the two sources are not alike.
 *
 * - Cosmic rays are everywhere and almost constant, so a dose is a rate times a
 *   time. The rate grows with the distance from the Sun and falls as the solar
 *   cycle rises. The fit uses Earth and cruise data only, and it gives the lunar
 *   surface to 7% and Gale crater to 2%.
 * - On a fast craft the cosmic ray rate per ship second is the rate at rest
 *   times a boost F(γ). The particles from ahead arrive faster and more often.
 * - Trapped particles are round four planets only, and they are five orders of
 *   magnitude worse. A Jupiter swing-by is cheap, so the planner offers it, and
 *   its cost is dose, not Δv. The model is a profile of three parameters on two
 *   anchors, good to a factor of four. That is enough, because a close pass
 *   gives thousands of grays either way.
 *
 * The fit and the belt profiles mirror `constants/radiation/{field,belt_field}.py`,
 * where they are fitted and checked against flown data. Keep the two in step by
 * hand. The numbers change only when a paper changes.
 *
 * Solar particle events are in neither model. Their fluence is lognormal, so a
 * mean is a bad summary. The risk is one large event during the trip, such as
 * that of August 1972.
 */

import { DAYS_PER_YEAR, J2000_JD } from '$lib/time/jd';
import { SEC_PER_DAY } from './constants';
import type { RapidityRate } from './interstellar';

/** Decimal year, which is the clock the solar cycle is phased against. */
export function decimalYearOf(jd: number): number {
	return 2000 + (jd - J2000_JD) / DAYS_PER_YEAR;
}

// --- galactic cosmic rays ----------------------------------------------------

/** Solar minimum, and the period. Cosmic rays peak at minimum, not maximum:
 *  the Sun sweeps them out of the inner system when it is most active. */
const SOLAR_MINIMUM_EPOCH = 2019.96;
const SOLAR_CYCLE_YEARS = 11.0;

/** How far the dose swings across a cycle — Guo's same Hohmann round trip at
 *  1.59 Sv near minimum against 0.65 Sv near maximum. */
const SOLAR_CYCLE_RATIO = 1.59 / 0.65;

/** Cosmic ray intensity climbs with distance from the Sun, fitted over 1 to
 *  9.5 au against Cassini's high-energy protons. */
const RADIAL_GRADIENT_PER_AU = 0.03;

/**
 * Free space at 1 au, averaged over a solar cycle, Sv/day. Fitted to RAD's
 * cruise reading, so it carries a real spacecraft's shielding — which for
 * cosmic rays is nearly the same as carrying none, a claim the lunar surface
 * check puts at under 10%.
 */
const REFERENCE_DOSE_SV_PER_DAY = 1.731e-3;

export function solarCycleFactor(decimalYear: number): number {
	const phase = (2 * Math.PI * (decimalYear - SOLAR_MINIMUM_EPOCH)) / SOLAR_CYCLE_YEARS;
	return Math.sqrt(SOLAR_CYCLE_RATIO) ** Math.cos(phase);
}

export function radialFactor(rAu: number): number {
	return 1 + RADIAL_GRADIENT_PER_AU * (rAu - 1);
}

/**
 * Fraction of the sky a body of `bodyRadiusKm` leaves open, seen from
 * `distanceKm` from its centre. Exact for isotropic flux, and the one term
 * here with nothing fitted. Standing on the surface gives a half, infinity
 * gives one — so surface, low orbit and free space are one formula, not three.
 */
export function openSkyFraction(bodyRadiusKm: number, distanceKm: number): number {
	if (distanceKm <= bodyRadiusKm) return 0.5;
	return 0.5 * (1 + Math.sqrt(1 - (bodyRadiusKm / distanceKm) ** 2));
}

/** Cosmic ray dose equivalent in free space at a point and a time, Sv/day. */
export function gcrDoseRateSvPerDay(jd: number, rAu: number): number {
	return REFERENCE_DOSE_SV_PER_DAY * solarCycleFactor(decimalYearOf(jd)) * radialFactor(rAu);
}

/** The range of distances the radial gradient is fitted over, au. */
const RADIAL_FIT_AU = { min: 1, max: 9.5 };

/** Distance of the heliopause, au. Voyager 1 crossed it at 121.6 au and
 *  Voyager 2 at 119.0 au. */
export const HELIOPAUSE_AU = 120;

/**
 * Cosmic ray dose past the heliopause, as a multiple of the dose at 1 au at
 * solar minimum. Mewaldt et al. 2005 (29th ICRC 2, 101), Table 1, extrapolated
 * to φ = 0 gives 1.92. The force-field model on the local interstellar spectra
 * of Corti et al. 2016 (ApJ 829, 8) gives 1.50 to 2.07. Cummings et al. 2016
 * (ApJ 831, 18) find no gradient past the heliopause, so the rate is the same
 * everywhere there.
 */
const INTERSTELLAR_DOSE_RATIO = 1.8;

/** Cosmic ray dose equivalent past the heliopause at rest, Sv/day. The Sun does
 *  not modulate the flux there. */
export const INTERSTELLAR_DOSE_SV_PER_DAY =
	REFERENCE_DOSE_SV_PER_DAY * Math.sqrt(SOLAR_CYCLE_RATIO) * INTERSTELLAR_DOSE_RATIO;

/** Cosmic ray dose equivalent at rest at a point of a crossing between two
 *  stars, Sv/day. Inside the heliopause the fit holds its value at the ends of
 *  its range. */
export function interstellarDoseRateSvPerDay(jd: number, rAu: number): number {
	if (rAu >= HELIOPAUSE_AU) return INTERSTELLAR_DOSE_SV_PER_DAY;
	const fitted = Math.min(Math.max(rAu, RADIAL_FIT_AU.min), RADIAL_FIT_AU.max);
	return gcrDoseRateSvPerDay(jd, fitted);
}

/**
 * The boost F against γ. F is the cosmic ray dose per ship second on a moving
 * craft over the dose at rest. It is between γ and γ², because the slow
 * particles of the rest frame arrive from ahead near c. It is the mean of
 * protons and helium, each with the coefficient for its direction of arrival.
 * It is the same quantity as the rate, a Q(L)-based dose equivalent. Past
 * γ = 30 the last slope continues.
 */
const COSMIC_RAY_BOOST_TABLE: readonly (readonly [gamma: number, boost: number])[] = [
	// Corti et al. 2016 (ApJ 829, 8) spectra; Sato et al. 2009 (PMB 54, 1997) and 2010 (PMB 55, 2235) coefficients.
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

/** A point of the boost table against the rapidity φ. */
interface BoostKnot {
	phi: number;
	boost: number;
	/** Slope of ln F against φ up to the next point. The last point keeps the
	 *  slope before it. */
	slope: number;
	/** The integral of F over φ from rest to this point. */
	fromRest: number;
}

/** ln F is linear in φ between the points, so each step of the integral is exact. */
const BOOST_KNOTS: readonly BoostKnot[] = (() => {
	const points = COSMIC_RAY_BOOST_TABLE.map(([gamma, boost]) => ({
		phi: Math.acosh(gamma),
		boost
	}));
	const knots: BoostKnot[] = [];
	for (let i = 0; i < points.length; i++) {
		const { phi, boost } = points[i];
		const [low, high] =
			i + 1 < points.length ? [points[i], points[i + 1]] : [points[i - 1], points[i]];
		const slope = Math.log(high.boost / low.boost) / (high.phi - low.phi);
		const previous = knots[i - 1];
		const fromRest = previous ? previous.fromRest + (boost - previous.boost) / previous.slope : 0;
		knots.push({ phi, boost, slope, fromRest });
	}
	return knots;
})();

function boostKnotAt(phi: number): BoostKnot {
	return BOOST_KNOTS.findLast((knot) => knot.phi <= phi) ?? BOOST_KNOTS[0];
}

/** The boost F at rapidity `phi`. */
export function cosmicRayBoost(phi: number): number {
	const knot = boostKnotAt(phi);
	return knot.boost * Math.exp(knot.slope * (phi - knot.phi));
}

/** The integral of F over the rapidity from rest to `phi`. */
export function cosmicRayBoostFromRest(phi: number): number {
	const knot = boostKnotAt(phi);
	return knot.fromRest + (knot.boost * Math.expm1(knot.slope * (phi - knot.phi))) / knot.slope;
}

/** The boost as a rate along a crossing. Its total is the ship time weighted by F, s. */
export const COSMIC_RAY_BOOST: RapidityRate = {
	at: cosmicRayBoost,
	fromRest: cosmicRayBoostFromRest
};

// --- trapped particles -------------------------------------------------------

/** The thinnest shielding the Europa lander study's dose curve draws, g/cm². */
export const BELT_REFERENCE_SHIELDING_G_CM2 = 0.11;

/** That curve falls two decades between the reference and 10 mm of aluminium. */
const BELT_SHIELDING_LENGTH_G_CM2 = (2.7 - BELT_REFERENCE_SHIELDING_G_CM2) / (2 * Math.LN10);

/**
 * Past the end of the source curve the exponential is bad extrapolation — at
 * 20 g/cm² it returns 1e-11 — because the electrons stop but their
 * bremsstrahlung doesn't. Held at the two decades the figure actually spans.
 * Consequence: this model can't tell a 5 g/cm² hull from a 20 g/cm² storm
 * shelter — everything a crew flies behind is on the floor. A belt dose for a
 * crewed ship is therefore an upper bound, and it's still lethal, which is
 * why the distinction hasn't been worth chasing.
 */
export const BELT_SHIELDING_FLOOR = 1e-2;

/** Surviving fraction behind `shieldingGCm2`, against the 0.11 reference. */
export function beltAttenuation(shieldingGCm2: number): number {
	const past = shieldingGCm2 - BELT_REFERENCE_SHIELDING_G_CM2;
	if (past <= 0) return 1;
	return Math.max(BELT_SHIELDING_FLOOR, Math.exp(-past / BELT_SHIELDING_LENGTH_G_CM2));
}

/**
 * Dose behind `shieldingGCm2`, relative to what a profile was quoted at. The
 * profiles don't share a reference — Jupiter's comes off a figure drawn at
 * 0.11 g/cm², Saturn's and Neptune's off JPL curves at 100 mils of aluminium —
 * so converting between them is the ratio of two points on one curve.
 */
export function beltShieldingFactor(shieldingGCm2: number, referenceGCm2: number): number {
	return beltAttenuation(shieldingGCm2) / beltAttenuation(referenceGCm2);
}

/** 100 mils of aluminium, the thickness JPL's engineering models are drawn at. */
export const JPL_SHELL_G_CM2 = 2.54 * 0.1 * 2.7;

/** Where Jupiter's MeV electrons maximise, in planetary radii. */
const JOVIAN_PEAK_L = 3.0;
/** Outer falloff, from Johnson's Europa-against-Callisto energy fluxes. */
const JOVIAN_OUTER_SLOPE = 5.3666;
/** Dose rate at the peak behind the reference shielding, Gy/day. Fitted to
 *  Pioneer 10's whole-pass dose. */
const JOVIAN_PEAK_GY_PER_DAY = 2.414e5;

/**
 * Absorbed dose rate at `lShell` planetary radii, Gy/day, behind the
 * reference shielding. Flat inside the peak rather than extrapolated inward:
 * the only measurement there is Pioneer 11's, a polar pass that can't
 * separate a radial decline from a latitude one. Flat is the conservative
 * reading, so a pass inside L = 3 is an upper bound.
 */
export function jovianBeltRateGyPerDay(lShell: number): number {
	return beltRateGyPerDay(BELT_PROFILES['naif-599'], lShell);
}

/**
 * How hard a planet's belt hits, against distance from its centre.
 *
 * `samples` are [planetary radii, Gy/day] ascending, interpolated log-log
 * because both axes span decades; outside the last, a power law of index
 * `outerSlope` (or the slope the last two samples already imply). Inside the
 * first, `flatInside` holds the rate — true only where nothing measured that
 * branch, which makes a close pass an upper bound rather than an estimate.
 */
export interface BeltProfile {
	samples: readonly (readonly [number, number])[];
	shieldingGCm2: number;
	outerSlope?: number;
	flatInside?: boolean;
}

/**
 * Mirrored from `constants/radiation/belt_field.py`, where each is sourced.
 * Jupiter is fitted with flown anchors behind it; Saturn and Neptune are read
 * off JPL's engineering models, so the shape is theirs. Uranus has no
 * published profile at all and stays absent rather than borrowing Neptune's.
 */
export const BELT_PROFILES: Readonly<Record<string, BeltProfile>> = {
	'naif-599': {
		samples: [[JOVIAN_PEAK_L, JOVIAN_PEAK_GY_PER_DAY]],
		outerSlope: JOVIAN_OUTER_SLOPE,
		shieldingGCm2: BELT_REFERENCE_SHIELDING_G_CM2,
		flatInside: true
	},
	'naif-699': {
		samples: [
			[2.55, 42.9],
			[5.95, 2.86],
			[9.47, 2.14e-3]
		],
		shieldingGCm2: JPL_SHELL_G_CM2,
		flatInside: true
	},
	'naif-899': {
		samples: [
			[2.2, 1.296e-3],
			[3.7, 3.456e-2],
			[5.0, 8.64e-3],
			[7.0, 0.1382],
			[9.0, 2.592e-2],
			[12.0, 1.728e-3],
			[18.0, 5.18e-5],
			[27.0, 7.78e-7]
		],
		shieldingGCm2: JPL_SHELL_G_CM2,
		flatInside: false
	}
};

/** Absorbed dose rate at `lShell`, behind the profile's own shielding. */
export function beltRateGyPerDay(profile: BeltProfile, lShell: number): number {
	if (lShell <= 0) return 0;
	const samples = profile.samples;
	const [firstL, firstRate] = samples[0];
	if (lShell <= firstL) {
		if (profile.flatInside || samples.length < 2) return firstRate;
		// Continue the innermost segment's slope rather than inventing a shape.
		const [secondL, secondRate] = samples[1];
		const index = Math.log(secondRate / firstRate) / Math.log(secondL / firstL);
		return firstRate * (lShell / firstL) ** index;
	}
	for (let step = 1; step < samples.length; step++) {
		const [lowL, lowRate] = samples[step - 1];
		const [highL, highRate] = samples[step];
		if (lShell <= highL) {
			const index = Math.log(highRate / lowRate) / Math.log(highL / lowL);
			return lowRate * (lShell / lowL) ** index;
		}
	}
	const [lastL, lastRate] = samples[samples.length - 1];
	let slope = profile.outerSlope;
	if (slope === undefined) {
		const [previousL, previousRate] = samples[samples.length - 2];
		slope = -Math.log(lastRate / previousRate) / Math.log(lastL / previousL);
	}
	return lastRate * (lShell / lastL) ** -slope;
}

/** Bodies whose belts have a dose profile. Uranus and Earth report a crossing
 *  and no figure, which is a better answer than a fabricated one. */
export const MODELLED_BELT_IDS: ReadonlySet<string> = new Set(Object.keys(BELT_PROFILES));

const PASS_STEPS = 512;

/**
 * Absorbed dose of one hyperbolic pass, grays. Integrated over true anomaly
 * with time from Kepler's equation, so weighting is by how long the pass
 * spends at each distance, not how far it travels there — the whole physics
 * of it: Pioneer 11 went three times closer to Jupiter than Pioneer 10 and
 * took a quarter of the dose, moving at 47 km/s.
 *
 * Every pass is treated as equatorial. A polar one crosses where the trapped
 * population is thinner — Pioneer 11's was, over-predicted here by about
 * four, the larger of the model's two known biases.
 */
export function beltPassDoseGy(
	profile: BeltProfile,
	periapsisKm: number,
	vInfinityKms: number,
	shieldingGCm2: number,
	radiusKm: number,
	muKm3S2: number
): number {
	if (!(periapsisKm > 0) || !(vInfinityKms > 0) || !(radiusKm > 0)) return 0;

	const semiMajor = -muKm3S2 / vInfinityKms ** 2;
	const eccentricity = 1 - periapsisKm / semiMajor;
	if (!(eccentricity > 1)) return 0;
	const semiLatus = periapsisKm * (1 + eccentricity);

	// Stop just short of the asymptote, where r runs away and the integrand to
	// zero anyway.
	const nuLimit = Math.acos(-1 / eccentricity) * 0.999;
	const meanMotionFactor = Math.sqrt((-semiMajor) ** 3 / muKm3S2);
	const tanHalf = Math.sqrt((eccentricity - 1) / (eccentricity + 1));

	const timeAt = (nu: number): number => {
		const tanhH = Math.min(0.999999999, Math.max(-0.999999999, tanHalf * Math.tan(nu / 2)));
		const anomaly = Math.atanh(tanhH);
		return meanMotionFactor * (eccentricity * Math.sinh(anomaly) - anomaly);
	};

	let total = 0;
	let previous = timeAt(-nuLimit);
	for (let step = 1; step <= PASS_STEPS; step++) {
		const nu = -nuLimit + (2 * nuLimit * step) / PASS_STEPS;
		const radius = semiLatus / (1 + eccentricity * Math.cos(nu));
		const now = timeAt(nu);
		total += (beltRateGyPerDay(profile, radius / radiusKm) * (now - previous)) / SEC_PER_DAY;
		previous = now;
	}

	return total * beltShieldingFactor(shieldingGCm2, profile.shieldingGCm2);
}

/**
 * Shielding a crewed pressure vessel is taken to sit behind, g/cm². Nothing
 * in the vehicle catalogue carries a shielding figure, and this is well past
 * the floor above, so the exact value changes no belt answer — it's here to
 * be named rather than assumed silently. Apollo's command module was around
 * 7; the ISS averages over 10.
 */
export const DEFAULT_SHIELDING_G_CM2 = 10;

/**
 * How far out the belt model can be, as a multiplying factor either way.
 * Measured, not assumed: the profile is normalised on one anchor (Pioneer
 * 10's pass), leaving two checks that land almost symmetrically either side —
 * Pioneer 11 over-predicted by 3.89, Europa's orbital rate under-predicted by
 * 3.80.
 *
 * That's the spread of two points, not a confidence interval, and shouldn't
 * be read as one. Likeliest reason they disagree: the Pioneers' dose was
 * largely protons, far more centrally peaked than the electrons Europa's
 * figure is made of, so one radial profile can't serve both populations.
 */
export const BELT_MODEL_UNCERTAINTY_FACTOR = 4;

// --- what it does to a person ------------------------------------------------

/**
 * Acute whole-body dose that kills half of those exposed within 60 days, Gy.
 * The untreated figure, the only one that means anything here: LD50/60 is
 * about 4.5 Gy with minimal care, over 6 Gy with supportive care, and
 * supportive care isn't available near Jupiter (CDC's clinician guidance on
 * acute radiation syndrome).
 *
 * It's a dose to bone marrow, and the belt figures are doses behind a hull,
 * so the comparison is rough in a knowable direction: Jupiter's belts are
 * electron-dominated, and multi-MeV electrons stop in about a centimetre of
 * tissue, so skin dose far exceeds marrow dose and this overstates what
 * marrow takes. Miller reached "lethal to man" regardless — even a
 * hundredfold reduction leaves tens of grays.
 */
export const LETHAL_DOSE_GY = 4.5;

/** An absorbed dose as a fraction of one lethal dose. */
export function lethalDoseFraction(gy: number): number {
	return gy / LETHAL_DOSE_GY;
}

/**
 * Added lifetime risk of a radiation-induced cancer, per sievert. ICRP 103's
 * detriment-adjusted nominal coefficient for adult workers, 4.1 × 10⁻² per
 * Sv — the working-age figure rather than the whole-population 5.5, since
 * nobody flies to Saturn as a child.
 *
 * Two things it is not: a low-LET coefficient derived largely from atomic
 * bomb survivors, while cosmic rays are heavy ions whose risk is uncertain by
 * a factor of a few even after the sievert's quality factor; and linear,
 * which is extrapolation above roughly 1 Sv — at the several Sv a long
 * crossing reaches, the figure is an order of magnitude, not a prediction.
 */
export const CANCER_RISK_PER_SV = 0.041;

/** Added lifetime cancer risk from a dose equivalent, as a 0-1 fraction. */
export function cancerRiskFraction(sv: number): number {
	return sv * CANCER_RISK_PER_SV;
}
