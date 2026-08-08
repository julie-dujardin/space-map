/**
 * A route is an ordered list of legs, each with a Δv price and a duration.
 *
 * The same structure serves three purposes: it is the itinerary the map draws,
 * it is the stacked Δv ladder, and its total is what a vehicle's capability is
 * checked against. Keeping them one object is what stops the ladder and the
 * trajectory from ever disagreeing.
 */

import type { TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { solveLambert } from './lambert';
import {
	arrivalCost,
	characteristicEnergy,
	departureCost,
	type ArrivalMode,
	type DepartureMode
} from './maneuvers';
import { elementsToState } from './state';
import { norm, sub } from './vec3';

export type LegKind = 'ascent' | 'injection' | 'cruise' | 'capture' | 'descent';

export interface RouteLeg {
	kind: LegKind;
	/** Δv this leg costs, km/s. Zero for a coast. */
	dvKms: number;
	/** How long the leg takes, days. Burns are treated as instantaneous. */
	days: number;
	/** Set when an atmosphere absorbed part of the leg rather than propellant. */
	aerobraked?: boolean;
}

export interface Route {
	departureId: string;
	targetId: string;
	departJd: number;
	arriveJd: number;
	tofDays: number;
	legs: RouteLeg[];
	/** Every leg's Δv, km/s. */
	totalDvKms: number;
	/** Total excluding ascent — what a craft already in orbit has to find. */
	inSpaceDvKms: number;
	/** Launch energy, km²/s² — the number launch vehicles are rated against. */
	c3Km2S2: number;
	vInfDepKms: number;
	vInfArrKms: number;
	departureMode: DepartureMode;
	arrivalMode: ArrivalMode;
}

export interface RouteOptions {
	departureMode?: DepartureMode;
	arrivalMode?: ArrivalMode;
	/** μ of the body both endpoints orbit, km³/s². Defaults to the Sun. */
	centralMu?: number;
	/** Solve the transfer clockwise about the frame's +Z axis. */
	retrograde?: boolean;
}

/**
 * Build the route departing at `departJd` and arriving `tofDays` later.
 *
 * Both bodies must be referenced to the same primary — this is a single
 * patched-conic leg, so a moon of another planet needs its own leg from that
 * planet rather than a direct solve.
 *
 * Returns null when no transfer arc exists for that pair of dates.
 */
export function buildRoute(
	departure: TravelBody,
	target: TravelBody,
	departJd: number,
	tofDays: number,
	options: RouteOptions = {}
): Route | null {
	const {
		departureMode = 'surface',
		arrivalMode = 'capture',
		centralMu = GM_SUN_KM3_S2,
		retrograde = false
	} = options;

	if (!(tofDays > 0)) return null;

	const arriveJd = departJd + tofDays;
	const from = elementsToState(departure.elements, departJd, centralMu);
	const to = elementsToState(target.elements, arriveJd, centralMu);
	if (!from || !to) return null;

	const arc = solveLambert(from.r, to.r, tofDays * SEC_PER_DAY, centralMu, retrograde);
	if (!arc) return null;

	const vInfDep = norm(sub(arc.v1, from.v));
	const vInfArr = norm(sub(arc.v2, to.v));
	if (!isFinite(vInfDep) || !isFinite(vInfArr)) return null;

	const dep = departureCost(departure, vInfDep, departureMode);
	const arr = arrivalCost(target, vInfArr, arrivalMode);

	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'cruise', dvKms: 0, days: tofDays });
	if (arrivalMode !== 'flyby') {
		legs.push({ kind: 'capture', dvKms: arr.captureKms, days: 0, aerobraked: arr.aerobraked });
	}
	if (arr.descentKms > 0) {
		legs.push({ kind: 'descent', dvKms: arr.descentKms, days: 0, aerobraked: arr.aerobraked });
	}

	const totalDvKms = legs.reduce((sum, leg) => sum + leg.dvKms, 0);

	return {
		departureId: departure.id,
		targetId: target.id,
		departJd,
		arriveJd,
		tofDays,
		legs,
		totalDvKms,
		inSpaceDvKms: totalDvKms - dep.ascentKms,
		c3Km2S2: characteristicEnergy(vInfDep),
		vInfDepKms: vInfDep,
		vInfArrKms: vInfArr,
		departureMode,
		arrivalMode
	};
}
