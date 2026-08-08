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
