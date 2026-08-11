/**
 * How much ionizing radiation a trajectory delivers.
 *
 * Two models that do not resemble each other, because the subject does not.
 *
 * Cosmic rays are everywhere and nearly constant, so a cruise dose is a rate
 * times a duration and the only interesting parts are how the rate climbs with
 * distance from the Sun and how it swings — inversely — with the solar cycle.
 * That model is fitted at Earth and in cruise and then reproduces the lunar
 * surface to 7% and Gale crater to 2% without having been shown either.
 *
 * Trapped particles are nowhere except around four planets, where they are
 * five orders of magnitude worse than anything else in this file. A swing-by
 * past Jupiter is the case that forces them in: it is a manoeuvre the planner
 * will propose unprompted because it is cheap, and its cost is not Δv. That
 * model is a three-parameter profile with two anchors and is good to a factor
 * of about four, which is enough, because the answer it returns for any close
 * pass is "some thousands of grays" and the conclusion does not move.
 *
 * Both are mirrored from `constants/radiation/{field,belt_field}.py`, which is
 * where they are fitted and where the flown measurements they answer to are
 * checked against them. Nothing here is fitted; these are the results. Keep the
 * two in step by hand — the numbers are few and they change when a paper does,
 * not when code does.
 *
 * Solar particle events are in neither. Their fluence distribution is lognormal,
 * so an expected value is a bad summary of the hazard, and folding one into a
 * rate would bury the thing that actually matters: the chance of catching an
 * August 1972 while you are out there.
 */

import { DAYS_PER_YEAR, J2000_JD } from '$lib/time/jd';
import { SEC_PER_DAY } from './constants';

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
 * `distanceKm` from its centre.
 *
 * Exact for an isotropic flux and the one term here with nothing fitted in it.
 * Standing on the surface gives a half and infinity gives one, which is what
 * makes surface, low orbit and free space one formula rather than three cases.
 */
export function openSkyFraction(bodyRadiusKm: number, distanceKm: number): number {
	if (distanceKm <= bodyRadiusKm) return 0.5;
	return 0.5 * (1 + Math.sqrt(1 - (bodyRadiusKm / distanceKm) ** 2));
}

/** Cosmic ray dose equivalent in free space at a point and a time, Sv/day. */
export function gcrDoseRateSvPerDay(jd: number, rAu: number): number {
	return REFERENCE_DOSE_SV_PER_DAY * solarCycleFactor(decimalYearOf(jd)) * radialFactor(rAu);
}

// --- trapped particles -------------------------------------------------------

/** The thinnest shielding the Europa lander study's dose curve draws, g/cm². */
export const BELT_REFERENCE_SHIELDING_G_CM2 = 0.11;

/** That curve falls two decades between the reference and 10 mm of aluminium. */
const BELT_SHIELDING_LENGTH_G_CM2 = (2.7 - BELT_REFERENCE_SHIELDING_G_CM2) / (2 * Math.LN10);

/**
 * Past the end of the source curve the exponential is bad extrapolation — at
 * 20 g/cm² it returns 1e-11 — because the electrons stop and their
 * bremsstrahlung does not. Held at the two decades the figure actually spans.
 *
 * The practical consequence is that this model cannot tell a 5 g/cm² hull from
 * a 20 g/cm² storm shelter: everything a crew flies behind is on the floor. A
 * belt dose quoted for a crewed ship is therefore an upper bound, and it is
 * still lethal, which is why the distinction has not been worth chasing.
 */
export const BELT_SHIELDING_FLOOR = 1e-2;

export function beltShieldingFactor(shieldingGCm2: number): number {
	const past = shieldingGCm2 - BELT_REFERENCE_SHIELDING_G_CM2;
	if (past <= 0) return 1;
	return Math.max(BELT_SHIELDING_FLOOR, Math.exp(-past / BELT_SHIELDING_LENGTH_G_CM2));
}

/** Where Jupiter's MeV electrons maximise, in planetary radii. */
const JOVIAN_PEAK_L = 3.0;
/** Outer falloff, from Johnson's Europa-against-Callisto energy fluxes. */
const JOVIAN_OUTER_SLOPE = 5.3666;
/** Dose rate at the peak behind the reference shielding, Gy/day. Fitted to
 *  Pioneer 10's whole-pass dose. */
const JOVIAN_PEAK_GY_PER_DAY = 2.414e5;

/**
 * Absorbed dose rate at `lShell` planetary radii, Gy/day, behind the reference
 * shielding.
 *
 * Flat inside the peak rather than extrapolated inward: the only measurement in
 * there is Pioneer 11's, and it was a polar pass, so it cannot separate a
 * radial decline from a latitude one. Flat is the conservative reading, and a
 * pass inside L = 3 is an upper bound.
 */
export function jovianBeltRateGyPerDay(lShell: number): number {
	if (lShell <= 0) return 0;
	if (lShell <= JOVIAN_PEAK_L) return JOVIAN_PEAK_GY_PER_DAY;
	return JOVIAN_PEAK_GY_PER_DAY * (lShell / JOVIAN_PEAK_L) ** -JOVIAN_OUTER_SLOPE;
}

/** Bodies whose belts have a dose profile. Jupiter is the only one anyone has
 *  published a body-absorbed dose for; the rest report a crossing and no
 *  figure, which is a better answer than a fabricated one. */
export const MODELLED_BELT_IDS: ReadonlySet<string> = new Set(['naif-599']);

const PASS_STEPS = 512;

/**
 * Absorbed dose of one hyperbolic pass, grays.
 *
 * Integrated over true anomaly with the time from Kepler's equation, so the
 * weighting is by how long the pass spends at each distance rather than how far
 * it travels there. That is the whole physics of the thing: Pioneer 11 went
 * three times closer to Jupiter than Pioneer 10 and took a quarter of the dose,
 * because it was moving at 47 km/s.
 *
 * Every pass is treated as equatorial. A polar one crosses where the trapped
 * population is thinner — Pioneer 11's was, and this over-predicts it by about
 * four, which is the larger of the model's two known biases.
 */
export function beltPassDoseGy(
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
		total += (jovianBeltRateGyPerDay(radius / radiusKm) * (now - previous)) / SEC_PER_DAY;
		previous = now;
	}

	return total * beltShieldingFactor(shieldingGCm2);
}

/**
 * Shielding a crewed pressure vessel is taken to sit behind, g/cm².
 *
 * Nothing in the vehicle catalogue carries a shielding figure, and this is well
 * past the floor above, so the exact value changes no belt answer — it is here
 * to be named rather than assumed silently. Apollo's command module was around
 * 7 and the ISS averages something over 10.
 */
export const DEFAULT_SHIELDING_G_CM2 = 10;

/**
 * How far out the belt model can be, as a multiplying factor either way.
 *
 * Measured rather than assumed. The profile is normalised on one anchor —
 * Pioneer 10's pass — which leaves two things to check it against, and they
 * land almost symmetrically either side: Pioneer 11 is over-predicted by 3.89
 * and Europa's orbital rate is under-predicted by 3.80.
 *
 * That is the spread of two points and not a confidence interval, and it should
 * not be read as one. The likeliest reason they disagree at all is that the
 * Pioneers' dose was largely protons, which are far more centrally peaked than
 * the electrons Europa's figure is made of, so one radial profile cannot serve
 * both populations.
 */
export const BELT_MODEL_UNCERTAINTY_FACTOR = 4;

// --- what it does to a person ------------------------------------------------

/**
 * Acute whole-body dose that kills half of those exposed within 60 days, Gy.
 *
 * The untreated figure, which is the only one that means anything here: LD50/60
 * is about 4.5 Gy with minimal care and over 6 Gy with supportive care, and
 * supportive care is not available near Jupiter. CDC's clinician guidance on
 * acute radiation syndrome.
 *
 * It is a dose to bone marrow, and the belt figures are doses behind a hull, so
 * the comparison is rough in a knowable direction: Jupiter's belts are
 * electron-dominated and multi-MeV electrons stop in about a centimetre of
 * tissue, so skin dose far exceeds marrow dose and this overstates what the
 * marrow takes. Miller reached "lethal to man" regardless, because even a
 * hundredfold reduction leaves tens of grays.
 */
export const LETHAL_DOSE_GY = 4.5;

/** An absorbed dose as a fraction of one lethal dose. */
export function lethalDoseFraction(gy: number): number {
	return gy / LETHAL_DOSE_GY;
}

/**
 * Added lifetime risk of a radiation-induced cancer, per sievert.
 *
 * ICRP 103's detriment-adjusted nominal coefficient for adult workers,
 * 4.1 × 10⁻² per Sv — the working-age figure rather than the whole-population
 * 5.5, because nobody flies to Saturn as a child.
 *
 * Two things it is not. It is a low-LET coefficient derived largely from the
 * atomic bomb survivors, and cosmic rays are heavy ions whose risk is uncertain
 * by a factor of a few even after the quality factor in the sievert. And it is
 * linear, which is an extrapolation above roughly 1 Sv — at the several Sv a
 * long crossing reaches, the figure is an order of magnitude and not a
 * prediction.
 */
export const CANCER_RISK_PER_SV = 0.041;

/** Added lifetime cancer risk from a dose equivalent, as a 0-1 fraction. */
export function cancerRiskFraction(sv: number): number {
	return sv * CANCER_RISK_PER_SV;
}
