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
	departureCost,
	orbitPeriapsisSpeed,
	parkingOrbit,
	type AeroAssist,
	type ArrivalCost,
	type ArrivalMode,
	surfaceSite,
	type DepartureMode,
	type EndOrbit
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
	/** The crossing under a drive too weak to burn: months of thrust reshaping the
	 *  orbit rather than a coast between two impulses. */
	| 'powered-cruise'
	/** Climbing out of one well and dropping into the other, both of them a spiral
	 *  of revolutions rather than a burn. */
	| 'spiral-out'
	| 'spiral-in'
	/** A swing-by past a third body. Free when the geometry allows it, which is
	 *  the whole point; the Δv is what the geometry could not supply. */
	| 'assist'
	| 'capture'
	/** Months of passes through the target's atmosphere, walking the orbit down.
	 *  The only leg that costs time without a burn or a crossing to show for it. */
	| 'aerobrake'
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
	/** The orbit each end was priced at, where one was named. Echoed like `aero`
	 *  so that drawing a trip does not have to be handed the choices again. */
	departureOrbit?: EndOrbit;
	targetOrbit?: EndOrbit;
	/** What was asked of the target's atmosphere. Reported as asked even where
	 *  the body had none to give, so the route says what trip it answers. */
	aero: AeroAssist;
	/** Fastest the craft meets that atmosphere at, km/s — what a heat shield is
	 *  rated against. Absent when it never does. */
	entrySpeedKms?: number;
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
	 * The drive a spiral route was flown by, when it is one.
	 *
	 * Present exactly when the route came out of `buildLowThrustRoute`, and it is
	 * what tells everything downstream that the impulsive yardstick does not
	 * apply here: no launch window on the porkchop, no excess speed at either
	 * end, and a Δv that is spent over years rather than at two instants. The
	 * two figures are what the shape can be rebuilt from — see `rebuildSpiral`.
	 */
	lowThrust?: { accelMs2: number; veKms: number };
	/**
	 * Fastest the craft is going anywhere on the crossing, km/s in the frame it is
	 * flown in. Constant-thrust routes only.
	 *
	 * Carried rather than read off the boost leg, which holds the Δv the drive
	 * spent and not the speed that bought: once gravity is in the crossing the two
	 * differ by everything the primary did and by the departure body's own motion.
	 */
	peakSpeedKms?: number;
	/**
	 * Where between flying flat out and coasting as long as the geometry allows
	 * this arc was asked to sit, 0 to 1. Constant-thrust routes only.
	 */
	coastFraction?: number;
	/**
	 * Unit vector the drive pointed along while boosting, in the transfer frame.
	 * Constant-thrust routes only; braking is exactly against it.
	 *
	 * The one thing about the crossing that a shooting solve found rather than
	 * derived, so it is the one thing drawing the arc cannot work out for itself.
	 * Three numbers spare the map a second Newton solve — and, more to the point,
	 * guarantee the line drawn is the arc that was priced rather than whichever
	 * root a re-solve happens to land on.
	 */
	thrustDir?: readonly [number, number, number];
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
	/** The orbit each end is met in. Absent means the standard parking orbit at
	 *  departure and whatever `arrivalMode` implies on arrival. */
	departureOrbit?: EndOrbit;
	targetOrbit?: EndOrbit;
	/**
	 * Latitude the trip leaves the ground from and the one it comes back down
	 * to, degrees, where the end is a place rather than a whole body. Only the
	 * latitude matters: how far round the body the site has turned changes when
	 * the launch happens, not what it costs.
	 */
	departureSiteLatDeg?: number;
	targetSiteLatDeg?: number;
	/** What to ask of the target's atmosphere. Defaults to using none of it. */
	aero?: AeroAssist;
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
 * The legs an arrival adds, in the order they are flown.
 *
 * Shared by all three builders because the arrival is the one part of a route
 * that does not care how the craft got there — a Lambert arc, a transfer
 * ellipse and a held drive all hand over the same speed at the same place.
 *
 * A burn nobody makes is not a step: a direct entry never enters an orbit, so
 * it has no insertion to list.
 */
export function arrivalLegs(cost: ArrivalCost, mode: ArrivalMode): RouteLeg[] {
	const legs: RouteLeg[] = [];
	if (mode !== 'flyby' && cost.captureKms > 0) {
		legs.push({ kind: 'capture', dvKms: cost.captureKms, days: 0, aerobraked: cost.aerobraked });
	}
	if (cost.aerobrakeDays > 0) {
		legs.push({ kind: 'aerobrake', dvKms: 0, days: cost.aerobrakeDays, aerobraked: true });
	}
	if (cost.descentKms > 0) {
		legs.push({ kind: 'descent', dvKms: cost.descentKms, days: 0, aerobraked: cost.aerobraked });
	}
	return legs;
}

/**
 * Everything the trip takes end to end, days — the crossing plus any campaign
 * flown after it. Every leg's duration, which is the cruise alone on the routes
 * that have nothing after arrival.
 */
export function routeDurationDays(route: Route): number {
	return route.legs.reduce((sum, leg) => sum + leg.days, 0);
}

/**
 * When the trip is over, JD.
 *
 * Not `arriveJd`, which is where the crossing ends: an aerobraking arrival is
 * captured on that date and then spends months walking the orbit down, with
 * nothing else happening until it is done. Anything asking whether a trip fits
 * inside a date has to ask about this one.
 */
export function routeEndJd(route: Route): number {
	return route.departJd + routeDurationDays(route);
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
		departureOrbit,
		targetOrbit,
		departureSiteLatDeg,
		targetSiteLatDeg,
		aero = 'none',
		centralMu = GM_SUN_KM3_S2,
		retrograde = false,
		systemPrimary
	} = options;

	if (!(tofDays > 0)) return null;
	if (systemPrimary) {
		return buildSystemRoute(departure, target, departJd, tofDays, {
			departureMode,
			arrivalMode,
			departureOrbit,
			targetOrbit,
			departureSiteLatDeg,
			targetSiteLatDeg,
			aero,
			outbound: systemPrimary === 'departure'
		});
	}

	const arriveJd = departJd + tofDays;
	const from = elementsToState(departure.elements, departJd, centralMu);
	const to = elementsToState(target.elements, arriveJd, centralMu);
	if (!from || !to) return null;

	const arc = solveLambert(from.r, to.r, tofDays * SEC_PER_DAY, centralMu, retrograde);
	if (!arc) return null;

	const vInfDepVec = sub(arc.v1, from.v);
	const vInfArrVec = sub(arc.v2, to.v);
	const vInfDep = norm(vInfDepVec);
	const vInfArr = norm(vInfArrVec);
	if (!isFinite(vInfDep) || !isFinite(vInfArr)) return null;

	const dep = departureCost(
		departure,
		vInfDep,
		departureMode,
		departureOrbit,
		surfaceSite(departure, departureSiteLatDeg, vInfDepVec)
	);
	const arr = arrivalCost(
		target,
		vInfArr,
		arrivalMode,
		aero,
		targetOrbit,
		surfaceSite(target, targetSiteLatDeg, vInfArrVec)
	);

	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'cruise', dvKms: 0, days: tofDays });
	legs.push(...arrivalLegs(arr, arrivalMode));

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
		arrivalMode,
		departureOrbit,
		targetOrbit,
		aero,
		entrySpeedKms: arr.entrySpeedKms
	};
}

interface SystemRouteOptions {
	departureMode: DepartureMode;
	arrivalMode: ArrivalMode;
	departureOrbit?: EndOrbit;
	targetOrbit?: EndOrbit;
	departureSiteLatDeg?: number;
	targetSiteLatDeg?: number;
	aero: AeroAssist;
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
	const {
		departureMode,
		arrivalMode,
		departureOrbit,
		targetOrbit,
		departureSiteLatDeg,
		targetSiteLatDeg,
		aero,
		outbound
	} = options;
	// Nothing here escapes, so there is no asymptote to hold: the arc can be
	// flown from a node of the satellite's orbit, and the site alone says how
	// steeply the plane has to lie.
	const departureSite = surfaceSite(departure, departureSiteLatDeg, null);
	const targetSite = surfaceSite(target, targetSiteLatDeg, null);
	const primary = outbound ? departure : target;
	const satellite = outbound ? target : departure;
	// Which end of the trip the primary is decides which orbit is its own.
	const primaryOrbit =
		(outbound ? (departureMode === 'surface' ? undefined : departureOrbit) : targetOrbit) ??
		parkingOrbit(primary);
	const satelliteOrbit = outbound ? targetOrbit : departureOrbit;
	const arriveJd = departJd + tofDays;

	// The satellite's distance is read at the end of the trip it is at: the far
	// end of an outbound arc, the near end of the way back.
	const state = relativeState(satellite, primary, outbound ? arriveJd : departJd);
	if (!state) return null;

	const rFar = norm(state.r);
	// The arc starts where the craft already is: leaving the Moon from a
	// stationary orbit is a shorter climb than leaving it from 200 km.
	const rNear = primaryOrbit.rPeriKm;
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
	const primaryBurn = arc.vNearKms - orbitPeriapsisSpeed(primary.mu, primaryOrbit);

	const legs: RouteLeg[] = [];
	let ascentKms = 0;
	if (departureMode === 'surface') {
		ascentKms = ascentDv(departure, departureSite);
		legs.push({ kind: 'ascent', dvKms: ascentKms, days: 0 });
	}
	legs.push({
		kind: 'injection',
		dvKms: outbound
			? primaryBurn
			: departureCost(satellite, vInf, departureMode, satelliteOrbit, departureSite).injectionKms,
		days: 0
	});
	legs.push({ kind: 'cruise', dvKms: 0, days: tofDays });

	const arr = outbound
		? arrivalCost(satellite, vInf, arrivalMode, aero, satelliteOrbit, targetSite)
		: arrivalCostFromSpeed(primary, arc.vNearKms, arrivalMode, aero, primaryOrbit, targetSite);
	legs.push(...arrivalLegs(arr, arrivalMode));

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
		arrivalMode,
		departureOrbit,
		targetOrbit,
		aero,
		entrySpeedKms: arr.entrySpeedKms
	};
}
