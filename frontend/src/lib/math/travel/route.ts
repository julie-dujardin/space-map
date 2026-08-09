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
import type { FlybyPass } from './flyby';
import { solveLambert } from './lambert';
import {
	arrivalCost,
	arrivalCostFromSpeed,
	ascentDv,
	characteristicEnergy,
	circularSpeed,
	departureCost,
	injectionDv,
	parkingRadiusKm,
	type ArrivalMode,
	type DepartureMode
} from './maneuvers';
import { elementsToState } from './state';
import { relativeState, solveRadialArc } from './system-transfer';
import { cross, dot, norm, sub } from './vec3';

export type LegKind =
	| 'ascent'
	| 'injection'
	| 'cruise'
	/** The two halves of a constant-thrust arc: everything before the flip, and
	 *  everything after it. Unlike a cruise these carry Δv as well as time. */
	| 'boost'
	| 'brake'
	/** A swing-by past a third body. Free when the geometry allows it, which is
	 *  the whole point; the Δv is what the geometry could not supply. */
	| 'assist'
	| 'capture'
	| 'descent';

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
	/**
	 * The acceleration the drive is held at for the whole crossing, m/s², on the
	 * routes that are flown that way rather than coasted.
	 *
	 * The figure and the fact are one field because the fact is never anything
	 * else: `buildConstantThrustRoute` refuses an acceleration that is not
	 * positive, so absent means coasted and present means held. These belong to
	 * no porkchop — there is no window to place one on, so nothing that reasons
	 * about departure dates should try.
	 */
	constantThrust?: number;
	/**
	 * The swing-bys flown on the way, in order. Absent on a direct transfer.
	 *
	 * A route with these has more than one cruise leg, so nothing may assume the
	 * legs are unique by kind.
	 */
	flybys?: FlybyPass[];
}

export interface RouteOptions {
	departureMode?: DepartureMode;
	arrivalMode?: ArrivalMode;
	/** μ of the body both endpoints orbit, km³/s². Defaults to the Sun. */
	centralMu?: number;
	/** Solve the transfer clockwise about the frame's +Z axis. */
	retrograde?: boolean;
	/**
	 * Set when the trip stays inside one system: the named end is the body the
	 * transfer orbits, and the other end is a satellite of it. There is no
	 * heliocentric arc between them and no escape at the primary's end, so the
	 * route is built from a transfer ellipse instead of a Lambert solve.
	 */
	systemPrimary?: 'departure' | 'target';
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
		retrograde = false,
		systemPrimary
	} = options;

	if (!(tofDays > 0)) return null;
	if (systemPrimary) {
		return buildSystemRoute(departure, target, departJd, tofDays, {
			departureMode,
			arrivalMode,
			outbound: systemPrimary === 'departure'
		});
	}

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

interface SystemRouteOptions {
	departureMode: DepartureMode;
	arrivalMode: ArrivalMode;
	/** True when leaving the primary for its satellite, false coming back. */
	outbound: boolean;
}

/**
 * Build a route between a body and one of its own satellites.
 *
 * Both directions are the same arc read in opposite senses, so both are priced
 * the same way: at the primary's end the craft is bound to it either way and
 * pays the difference between the transfer's speed and the parking orbit's; at
 * the satellite's end it crosses a sphere of influence, which is the ordinary
 * interplanetary arrival and departure.
 */
function buildSystemRoute(
	departure: TravelBody,
	target: TravelBody,
	departJd: number,
	tofDays: number,
	options: SystemRouteOptions
): Route | null {
	const { departureMode, arrivalMode, outbound } = options;
	const primary = outbound ? departure : target;
	const satellite = outbound ? target : departure;
	const arriveJd = departJd + tofDays;

	// The satellite's distance is read at the end of the trip it is at: the far
	// end of an outbound arc, the near end of the way back.
	const state = relativeState(satellite, primary, outbound ? arriveJd : departJd);
	if (!state) return null;

	const rFar = norm(state.r);
	const rNear = parkingRadiusKm(primary);
	const arc = solveRadialArc(primary.mu, rNear, rFar, tofDays);
	if (!arc) return null;

	// The satellite's own motion, split the same way as the arc's: how fast it is
	// climbing, and how fast it is going round.
	const satRadial = dot(state.r, state.v) / rFar;
	const satTangential = norm(cross(state.r, state.v)) / rFar;
	const vInf = Math.hypot(arc.vFarRadialKms - satRadial, arc.vFarTangentialKms - satTangential);
	if (!isFinite(vInf)) return null;

	// At the primary the craft never leaves, so the burn is measured against the
	// parking orbit rather than against an escape.
	const primaryBurn = arc.vNearKms - circularSpeed(primary.mu, rNear);

	const legs: RouteLeg[] = [];
	let ascentKms = 0;
	if (departureMode === 'surface') {
		ascentKms = ascentDv(departure);
		legs.push({ kind: 'ascent', dvKms: ascentKms, days: 0 });
	}
	legs.push({
		kind: 'injection',
		dvKms: outbound ? primaryBurn : injectionDv(satellite.mu, parkingRadiusKm(satellite), vInf),
		days: 0
	});
	legs.push({ kind: 'cruise', dvKms: 0, days: tofDays });

	const arr = outbound
		? arrivalCost(satellite, vInf, arrivalMode)
		: arrivalCostFromSpeed(primary, arc.vNearKms, arrivalMode);
	if (arrivalMode !== 'flyby') {
		legs.push({ kind: 'capture', dvKms: arr.captureKms, days: 0, aerobraked: arr.aerobraked });
	}
	if (arr.descentKms > 0) {
		legs.push({ kind: 'descent', dvKms: arr.descentKms, days: 0, aerobraked: arr.aerobraked });
	}

	const totalDvKms = legs.reduce((sum, leg) => sum + leg.dvKms, 0);
	if (!isFinite(totalDvKms)) return null;

	return {
		departureId: departure.id,
		targetId: target.id,
		departJd,
		arriveJd,
		tofDays,
		legs,
		totalDvKms,
		inSpaceDvKms: totalDvKms - ascentKms,
		// The arc stays bound to the primary, so its C3 is negative — which is what
		// a launch to the Moon is quoted at, and what separates it from an escape.
		c3Km2S2: outbound ? -primary.mu * arc.inverseAKm : characteristicEnergy(vInf),
		vInfDepKms: outbound ? 0 : vInf,
		vInfArrKms: outbound ? vInf : 0,
		departureMode,
		arrivalMode
	};
}
