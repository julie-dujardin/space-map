/**
 * Real bodies for the trajectory tests, so the assertions can be checked
 * against published mission numbers rather than against the code itself.
 *
 * Elements are JPL's approximate Keplerian elements for the major planets at
 * J2000; GM and radii are IAU/SPICE values. Good to a fraction of a percent,
 * which is well inside what a Δv estimate needs.
 */

import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM } from '$lib/math/units';
import type { TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';

export const J2000 = 2451545.0;
const RAD2DEG = 180 / Math.PI;

function meanMotion(aAu: number): number {
	const aKm = aAu * AU_KM;
	return Math.sqrt(GM_SUN_KM3_S2 / (aKm * aKm * aKm)) * RAD2DEG * SEC_PER_DAY;
}

/** JPL publishes mean longitude and longitude of perihelion; elements want M and ω. */
function planetElements(
	aAu: number,
	e: number,
	i: number,
	meanLongitude: number,
	perihelionLongitude: number,
	om: number
): OrbitalElements {
	return {
		a: aAu,
		e,
		i,
		om,
		w: perihelionLongitude - om,
		ma: meanLongitude - perihelionLongitude,
		n: meanMotion(aAu),
		epoch: J2000
	};
}

export const EARTH: TravelBody = {
	id: 'naif-399',
	mu: 398600.4418,
	muEstimated: false,
	radiusKm: 6371.0,
	surfacePressureBar: 1.013,
	elements: planetElements(1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0)
};

export const MARS: TravelBody = {
	id: 'naif-499',
	mu: 42828.37,
	muEstimated: false,
	radiusKm: 3389.5,
	surfacePressureBar: 0.00636,
	elements: planetElements(
		1.52371034,
		0.0933941,
		1.84969142,
		-4.55343205,
		-23.94362959,
		49.55953891
	)
};

export const VENUS: TravelBody = {
	id: 'naif-299',
	mu: 324858.592,
	muEstimated: false,
	radiusKm: 6051.8,
	surfacePressureBar: 92,
	elements: planetElements(
		0.72333566,
		0.00677672,
		3.39467605,
		181.9790995,
		131.60246718,
		76.67984255
	)
};

export const JUPITER: TravelBody = {
	id: 'naif-599',
	mu: 1.26686534e8,
	muEstimated: false,
	radiusKm: 69911,
	elements: planetElements(5.202887, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909)
};

export const SATURN: TravelBody = {
	id: 'naif-699',
	mu: 3.7931187e7,
	muEstimated: false,
	radiusKm: 58232,
	elements: planetElements(
		9.53667594,
		0.05386179,
		2.48599187,
		49.95424423,
		92.59887831,
		113.66242448
	)
};

/**
 * An escaping probe — Voyager 2's heliocentric osculating orbit, rounded. It is
 * hyperbolic, so there is no semi-major axis to scale a transfer against and no
 * period to align with: the pair never repeats and the trip is a chase.
 */
export const ESCAPING_PROBE: TravelBody = {
	id: 'probe-49000448',
	mu: 1e-9,
	muEstimated: true,
	radiusKm: 0.01,
	elements: {
		a: -3.99,
		e: 6.29,
		i: 78.8,
		om: 101.7,
		w: 130.1,
		ma: 1000,
		n: meanMotion(3.99),
		epoch: J2000
	}
};

/**
 * A parabolic comet — the Great Comet of 1264, as SBDB has it and as the export
 * ships it. Most of the comet catalogue looks like this: e fixed at 1, and q/tp
 * in place of the a/ma/n an elliptical fit would carry.
 */
export const PARABOLIC_COMET: TravelBody = {
	id: 'spkid-1000616',
	mu: 1e-9,
	muEstimated: true,
	radiusKm: 1,
	elements: {
		a: 0,
		e: 1,
		i: 16.4,
		om: 151.04,
		w: 159.71,
		ma: 0,
		n: 0,
		epoch: 2182934.79,
		q: 0.8249,
		tp: 2182934.79
	}
};

/**
 * Earth and its Moon the way the export describes them: both referred to the
 * barycentre they share, half a turn apart, with the barycentre 4,674 km from
 * Earth's centre — most of the way out to a parking orbit, which is why a lunar
 * transfer has to difference the two rather than use either alone.
 *
 * Circular, so the separation holds at the semi-major axis of the real pair and
 * the Apollo figures the route is checked against are the textbook ones.
 */
const MOON_SEMI_MAJOR_KM = 384748;
const MOON_MU = 4902.8;
const EARTH_MU = 398600.4418;
const EARTH_BARYCENTRIC_KM = (MOON_SEMI_MAJOR_KM * MOON_MU) / (EARTH_MU + MOON_MU);
/** Sidereal month, deg/day — the pair's shared mean motion. */
const LUNAR_MEAN_MOTION = 13.176358;

function barycentric(aKm: number, ma: number): OrbitalElements {
	return { a: aKm / AU_KM, e: 0, i: 0, om: 0, w: 0, ma, n: LUNAR_MEAN_MOTION, epoch: J2000 };
}

export const EARTH_BARYCENTRIC: TravelBody = {
	id: 'naif-399',
	mu: EARTH_MU,
	muEstimated: false,
	radiusKm: 6371.0,
	surfacePressureBar: 1.013,
	elements: barycentric(EARTH_BARYCENTRIC_KM, 180),
	parentId: 'naif-3'
};

export const MOON_BARYCENTRIC: TravelBody = {
	id: 'naif-301',
	mu: MOON_MU,
	muEstimated: false,
	radiusKm: 1737.4,
	elements: barycentric(MOON_SEMI_MAJOR_KM - EARTH_BARYCENTRIC_KM, 0),
	parentId: 'naif-3'
};

/**
 * Two Galilean moons as the export describes them — jovicentric elements about
 * the Jupiter barycentre, at a 2026 epoch.
 *
 * Neither is the body the transfer goes round, so this is the sibling case: an
 * ordinary two-orbit transfer whose central mass is Jupiter's rather than the
 * Sun's, and whose whole timescale is days instead of months.
 */
const JOVIAN_EPOCH = 2461240.5;

export const IO: TravelBody = {
	id: 'naif-501',
	mu: 5959.916,
	muEstimated: false,
	radiusKm: 1821.6,
	elements: {
		a: 0.002821095942063092,
		e: 0.004467848063025687,
		i: 2.22252894564728,
		om: 338.46326060018174,
		w: 104.32837716252135,
		ma: 62.73808142330633,
		n: 203.2505150524944,
		epoch: JOVIAN_EPOCH
	},
	parentId: 'naif-5'
};

export const EUROPA: TravelBody = {
	id: 'naif-502',
	mu: 3202.739,
	muEstimated: false,
	radiusKm: 1560.8,
	elements: {
		a: 0.004485783212056366,
		e: 0.009414402373766022,
		i: 2.096511880154911,
		om: 326.08339255065107,
		w: 291.8086773897665,
		ma: 33.446435806735714,
		n: 101.36803252565768,
		epoch: JOVIAN_EPOCH
	},
	parentId: 'naif-5'
};

/** Airless, and the one ascent with a flight-proven Δv to check the model against. */
export const MOON: TravelBody = {
	id: 'naif-301',
	mu: 4902.8,
	muEstimated: false,
	radiusKm: 1737.4,
	elements: {
		a: 384400 / AU_KM,
		e: 0.0549,
		i: 5.145,
		om: 125.08,
		w: 318.15,
		ma: 135.27,
		n: 13.176358,
		epoch: J2000
	},
	parentId: 'naif-399'
};
