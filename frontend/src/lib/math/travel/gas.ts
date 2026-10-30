/**
 * The interstellar gas that a fast craft sweeps up on a crossing between two
 * stars.
 *
 * In the ship frame the gas is a beam from straight ahead at γβc, with
 * (γ − 1) m_p c² per nucleon. Each helium nucleus counts as four protons of the
 * same speed. So the dose per unit of path is the nucleons per volume times the
 * dose per proton.
 *
 * - The dose is behind the light hull of the cosmic ray row, 10 g/cm² of
 *   aluminium, with no frontal shield.
 * - It is a Q(L)-based dose equivalent, the same quantity as the cosmic ray row.
 * - Below 5.8 MeV per nucleon (0.11 c) the hull stops the protons before they
 *   make (p,n) neutrons, so the dose is zero. Helium (α,n) starts lower, but no
 *   source gives its yield.
 * - The hull strips every atom, so the ionization of the gas has no effect on
 *   the dose.
 */

import { SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import type { RapidityRate } from './interstellar';

/**
 * Hydrogen nuclei per cm³ along a crossing, neutral and ionized. The gas and the
 * dust both use it.
 *
 * Within 4 pc the mean neutral density along the sight lines is about 0.10, and
 * about a quarter of the hydrogen is ionized, so the total is 0.13. Farther out
 * the columns stop growing, so the value is too high there. The gas at the Sun
 * is denser (0.195 neutral), but that is a local value.
 * Linsky et al. 2022 (AJ 164, 106) and 2025 (ApJ 980, 202); Swaczyna et al. 2020 (ApJ 903, 48).
 */
export const INTERSTELLAR_N_H_CM3 = 0.13;

/** Helium nuclei per hydrogen nucleus (Slavin & Frisch 2008; Bzowski et al. 2019). */
const HE_PER_H = 0.1;

/** Nucleons per cm³ of the beam. */
const NUCLEONS_PER_CM3 = INTERSTELLAR_N_H_CM3 * (1 + 4 * HE_PER_H);

/** Rest energy of the proton, MeV. */
const PROTON_MEV = 938.272;

const C_CM_S = SPEED_OF_LIGHT_KM_S * 1e5;

const SV_PER_PSV = 1e-12;

/**
 * The dose behind the hull per proton from straight ahead, pSv cm², against the
 * kinetic energy per nucleon, MeV. Below 100 MeV only neutrons pass the hull
 * (good to a factor of about 3). From 100 to 120 MeV the protons start to pass,
 * so the dose jumps. Above 120 MeV it is good to ±30%.
 */
const HULL_DOSE_TABLE: readonly (readonly [tMeV: number, dose: number])[] = [
	// Sato et al. 2009 and 2010, NIST PSTAR, Tesch via Cossairt (TM-1834), Agosteo et al. 2007 (NIM B 265, 581).
	[5.8, 0],
	[7, 0.048],
	[10, 0.099],
	[15, 0.3],
	[20, 0.67],
	[30, 2.08],
	[50, 7.9],
	[70, 20.6],
	[100, 104],
	[102, 416],
	[110, 774],
	[120, 1020],
	[150, 1590],
	[200, 1410],
	[300, 906],
	[500, 838],
	[1000, 1160],
	[2000, 1230],
	[5000, 1430],
	[10000, 1490]
];

/** The segment of the table that holds `tMeV`. Past the last point, the last one. */
function segmentAt(tMeV: number): number {
	return Math.min(
		HULL_DOSE_TABLE.findLastIndex(([t]) => t <= tMeV),
		HULL_DOSE_TABLE.length - 2
	);
}

/** The log-log slope of segment `i`. */
function slopeOf(i: number): number {
	const [t0, d0] = HULL_DOSE_TABLE[i];
	const [t1, d1] = HULL_DOSE_TABLE[i + 1];
	return Math.log(d1 / d0) / Math.log(t1 / t0);
}

/** The integral of the dose over segment `i`, from its start to `tMeV`. The
 *  first segment is linear from the threshold; no other slope is −1. */
function segmentFromStart(i: number, tMeV: number): number {
	const [t0, d0] = HULL_DOSE_TABLE[i];
	if (i === 0) {
		const [t1, d1] = HULL_DOSE_TABLE[1];
		return (d1 * (tMeV - t0) ** 2) / (2 * (t1 - t0));
	}
	const s = slopeOf(i);
	return ((d0 * t0) / (s + 1)) * ((tMeV / t0) ** (s + 1) - 1);
}

/** The integral of the dose from rest to each point of the table, pSv cm² MeV.
 *  It is the exact integral of the interpolation, so that a burn and a coast at
 *  one speed agree. */
const FROM_REST_AT_POINT: readonly number[] = HULL_DOSE_TABLE.reduce<number[]>(
	(sums, [t], i) => [...sums, i === 0 ? 0 : sums[i - 1] + segmentFromStart(i - 1, t)],
	[]
);

/** The dose behind the hull per proton of `tMeV`, pSv cm². It is zero up to the
 *  threshold, linear to the next point and log-log after it. Past the last
 *  point the last slope continues. */
export function hullDosePerProton(tMeV: number): number {
	const [zero, first] = HULL_DOSE_TABLE;
	if (tMeV <= zero[0]) return 0;
	if (tMeV <= first[0]) return (first[1] * (tMeV - zero[0])) / (first[0] - zero[0]);
	const i = segmentAt(tMeV);
	const [t0, d0] = HULL_DOSE_TABLE[i];
	return d0 * (tMeV / t0) ** slopeOf(i);
}

/** The integral of {@link hullDosePerProton} over the kinetic energy from rest
 *  to `tMeV`, pSv cm² MeV. */
export function hullDoseFromRest(tMeV: number): number {
	if (tMeV <= HULL_DOSE_TABLE[0][0]) return 0;
	const i = segmentAt(tMeV);
	return FROM_REST_AT_POINT[i] + segmentFromStart(i, tMeV);
}

/** Kinetic energy per nucleon at rapidity `phi`, MeV. */
export function gasKineticMeV(phi: number): number {
	return 2 * Math.sinh(phi / 2) ** 2 * PROTON_MEV;
}

/**
 * The gas dose behind the hull as a rate along a crossing, Sv per ship second.
 * Over a burn the path is (c²/a) dγ, so the dose from rest is a closed form of
 * the integral of the table.
 */
export const GAS_DOSE: RapidityRate = {
	at: (phi) =>
		NUCLEONS_PER_CM3 * C_CM_S * Math.sinh(phi) * hullDosePerProton(gasKineticMeV(phi)) * SV_PER_PSV,
	fromRest: (phi) =>
		((NUCLEONS_PER_CM3 * C_CM_S * hullDoseFromRest(gasKineticMeV(phi))) / PROTON_MEV) * SV_PER_PSV
};
