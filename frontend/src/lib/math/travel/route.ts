/**
 * A route is an ordered list of legs, each with a Δv price and a duration. One
 * object serves three purposes — the map's itinerary, the stacked Δv ladder,
 * and the total a vehicle's capability is checked against — which is what
 * stops them from ever disagreeing.
 */

import type { TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import type { FlybyPass } from './flyby';
import { solveLambert } from './lambert';
import {
	aeroPassRadiusKm,
	arrivalCost,
	arrivalCostFromSpeed,
	ascentDv,
	asymptoteTurnDeg,
	canAeroBrake,
	characteristicEnergy,
	combinedBurn,
	departureCost,
	NO_ARRIVAL_COST,
	orbitJoinRadiusKm,
	orbitPeriodHours,
	orbitSpeedAtRadius,
	parkingOrbit,
	parkingRadiusKm,
	periapsisBurnWithTurn,
	planeTurnDeg,
	type AeroAssist,
	type ArrivalCost,
	type ArrivalMode,
	surfaceSite,
	type DepartureMode,
	type EndOrbit
} from './maneuvers';
import { equatorialTiltDeg } from './body';
import { endTurn } from './passage-node';
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
	/** The burn that cancels the speed the craft closes on another craft with.
	 *  What an insertion is to a body, this is to something with no well. */
	| 'rendezvous'
	/** One braking pass through the target's atmosphere doing the whole
	 *  insertion at once — the aero half of an aerocapture, costing nothing. */
	| 'aero-pass'
	/** Months of passes through the target's atmosphere, walking the orbit down.
	 *  The only leg that costs time without a burn or a crossing to show for it. */
	| 'aerobrake'
	/** The engine burn after the atmosphere's part: lifting periapsis clear of
	 *  the air, into the orbit that was asked for. */
	| 'raise'
	| 'descent';

export interface RouteLeg {
	kind: LegKind;
	/** Δv this leg costs, km/s. Zero for a coast. */
	dvKms: number;
	/** How long the leg takes, days. Burns are treated as instantaneous. */
	days: number;
	/** Set when an atmosphere absorbed part of the leg rather than propellant. */
	aerobraked?: boolean;
	/** Δv the atmosphere removed on this leg, km/s — the aero legs only. */
	absorbedKms?: number;
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
	/** Where the arc runs, on a trip between two orbits about one body. Echoed
	 *  rather than worked out again by the drawing: the plane and the radii it
	 *  joins at depend on the launch site, which no route carries. */
	orbitChange?: OrbitChangeEnds;
	/** What was asked of the target's atmosphere. Reported as asked even where
	 *  the body had none to give, so the route says what trip it answers. */
	aero: AeroAssist;
	/** Fastest the craft meets that atmosphere at, km/s — what a heat shield is
	 *  rated against. Absent when it never does. */
	entrySpeedKms?: number;
	/**
	 * The acceleration the drive is held at for the whole crossing, m/s², on
	 * routes flown that way rather than coasted. `buildConstantThrustRoute`
	 * refuses a non-positive acceleration, so absent means coasted and present
	 * means held. Belongs to no porkchop — there's no window to place one on.
	 */
	constantThrust?: number;
	/**
	 * The drive a spiral route was flown by, when it is one. Present exactly
	 * when the route came from `buildLowThrustRoute`: it tells everything
	 * downstream the impulsive yardstick doesn't apply — no launch window, no
	 * excess speed at either end, Δv spent over years not instants. These two
	 * figures are what the shape rebuilds from — see `rebuildSpiral`.
	 */
	lowThrust?: { accelMs2: number; veKms: number };
	/**
	 * Fastest the craft goes anywhere on the crossing, km/s in the frame it's
	 * flown in. Constant-thrust routes only. Carried rather than read off the
	 * boost leg, which holds Δv spent, not speed bought — once gravity is in
	 * the crossing the two differ by the primary's pull and the departure
	 * body's own motion.
	 */
	peakSpeedKms?: number;
	/**
	 * Where between flying flat out and coasting as long as the geometry allows
	 * this arc was asked to sit, 0 to 1. Constant-thrust routes only.
	 */
	coastFraction?: number;
	/**
	 * Unit vector the drive pointed along while boosting, in the transfer
	 * frame. Constant-thrust routes only; braking is exactly against it. The
	 * one thing a shooting solve found rather than derived, so drawing the arc
	 * can't work it out — these three numbers spare a second Newton solve and
	 * guarantee the line drawn is the arc that was priced, not a re-solve's
	 * arbitrary root.
	 */
	thrustDir?: readonly [number, number, number];
	/**
	 * The swing-bys flown on the way, in order. Absent on a direct transfer. A
	 * route with these has more than one cruise leg, so legs aren't unique by
	 * kind.
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
	/**
	 * Set when both ends are the same body: the arc joins two of its own orbits
	 * rather than crossing to another. Nothing is escaped and nothing is caught
	 * up with, so neither a Lambert solve nor a satellite's position applies.
	 */
	orbitChange?: boolean;
}

/**
 * The legs an arrival adds, in the order they are flown. Shared by all three
 * builders because the arrival doesn't care how the craft got there — a
 * Lambert arc, a transfer ellipse and a held drive all hand over the same
 * speed at the same place. A burn nobody makes is not a step: a direct entry
 * never enters an orbit, so it has no insertion to list.
 */
export function arrivalLegs(cost: ArrivalCost, mode: ArrivalMode): RouteLeg[] {
	const legs: RouteLeg[] = [];
	// The engine's steps and the atmosphere's are separate legs, in flight
	// order: an aerocapture pass is its own step before the raise that follows
	// it, and an aerobraking campaign sits between its insertion and walk-out.
	// A direct entry stays one descent — the pass and the landing are one fall.
	if (mode !== 'flyby' && cost.aerobraked && cost.aerobrakeDays === 0 && mode !== 'landing') {
		legs.push({
			kind: 'aero-pass',
			dvKms: 0,
			days: 0,
			aerobraked: true,
			absorbedKms: cost.absorbedKms
		});
	}
	const engine = cost.captureKms - cost.raiseKms;
	if (mode !== 'flyby' && engine > 0) {
		legs.push({ kind: mode === 'rendezvous' ? 'rendezvous' : 'capture', dvKms: engine, days: 0 });
	}
	if (cost.aerobrakeDays > 0) {
		legs.push({
			kind: 'aerobrake',
			dvKms: 0,
			days: cost.aerobrakeDays,
			aerobraked: true,
			absorbedKms: cost.absorbedKms
		});
	}
	if (cost.raiseKms > 0) {
		legs.push({ kind: 'raise', dvKms: cost.raiseKms, days: 0 });
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
 * When the trip is over, JD. Not `arriveJd`, where the crossing ends: an
 * aerobraking arrival is captured on that date and spends months walking the
 * orbit down before anything else happens. Anything asking whether a trip fits
 * a date must ask about this one instead.
 */
export function routeEndJd(route: Route): number {
	return route.departJd + routeDurationDays(route);
}

/**
 * Build the route departing at `departJd` and arriving `tofDays` later. Both
 * bodies must be referenced to the same primary — a single patched-conic leg,
 * so a moon of another planet needs its own leg from that planet rather than a
 * direct solve. Returns null when no transfer arc exists for those dates.
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
		systemPrimary,
		orbitChange
	} = options;

	if (!(tofDays > 0)) return null;
	if (orbitChange) {
		return buildOrbitChangeRoute(departure, departJd, tofDays, {
			departureMode,
			arrivalMode,
			departureOrbit,
			targetOrbit,
			departureSiteLatDeg,
			targetSiteLatDeg,
			aero
		});
	}
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

	// What each end owes for the plane it has to be reached in: nothing where the
	// orbit is free to swing its nodes under the asymptote, the shortfall where it
	// leans too little to hold it, and the whole angle between two forced planes
	// where the orbit has said where its own low point sits.
	const dep = departureCost(
		departure,
		vInfDep,
		departureMode,
		departureOrbit,
		surfaceSite(departure, departureSiteLatDeg, vInfDepVec),
		endTurn({ body: departure, orbit: departureOrbit, vInf: vInfDepVec, outward: true })
	);
	const arr = arrivalCost(
		target,
		vInfArr,
		arrivalMode,
		aero,
		targetOrbit,
		surfaceSite(target, targetSiteLatDeg, vInfArrVec),
		endTurn({
			body: target,
			orbit: targetOrbit,
			vInf: vInfArrVec,
			// An aerocaptured arrival never falls to the orbit's own low point: the
			// pass is the insertion, and it is flown in the air.
			rPeriKm: capturedByAir(target, aero, targetOrbit),
			outward: false
		})
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
 * Build a route between a body and one of its own satellites. Both directions
 * are the same arc read in opposite senses, priced the same way: at the
 * primary's end the craft is bound to it either way and pays the difference
 * against the parking orbit's speed; at the satellite's end it crosses a
 * sphere of influence, the ordinary interplanetary arrival and departure.
 */
/** Radius an arrival's passage is really flown at, km. An aerocapture never
 *  reaches the orbit's own low point — the pass is the insertion, made in the
 *  air — so the plane it can be flown in is settled down there. */
function capturedByAir(
	body: TravelBody,
	aero: AeroAssist,
	orbit: EndOrbit | undefined
): number | undefined {
	if (aero !== 'aerocapture' || !canAeroBrake(body)) return orbit?.rPeriKm;
	return aeroPassRadiusKm(body);
}

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

	// The arc's plane has to hold the satellite where the crossing meets it, so
	// a named primary orbit that leans less than the satellite's declination
	// owes the shortfall as a turn.
	const primaryTurn = asymptoteTurnDeg(primaryOrbit, equatorialTiltDeg(primary, state.r));
	// At the primary the craft never leaves, so the burn is measured against the
	// parking orbit rather than against an escape.
	const primaryBurn = periapsisBurnWithTurn(primary.mu, primaryOrbit, arc.vNearKms, {
		deg: primaryTurn
	});

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
		: arrivalCostFromSpeed(primary, arc.vNearKms, arrivalMode, aero, primaryOrbit, targetSite, {
				deg: primaryTurn
			});
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

interface OrbitChangeOptions {
	departureMode: DepartureMode;
	arrivalMode: ArrivalMode;
	departureOrbit?: EndOrbit;
	targetOrbit?: EndOrbit;
	departureSiteLatDeg?: number;
	targetSiteLatDeg?: number;
	aero: AeroAssist;
}

/** Radii closer than this are one radius: the trip is a single burn where the
 *  two orbits already meet, not an arc between them — and two ends that agree
 *  on both radii are the same orbit, which is not a trip at all. */
export const SAME_RADIUS_KM = 1;

/** The two orbits a same-body trip joins, and where the arc between them runs. */
export interface OrbitChangeEnds {
	from: EndOrbit;
	to: EndOrbit;
	/** Radius the craft leaves its own orbit at, and the one it meets the other
	 *  orbit at, km. */
	rFromKm: number;
	rToKm: number;
	/** True when the arc climbs away from the body, false when it comes down. */
	climb: boolean;
	/** True when both ends sit at one radius, so a single burn joins them. */
	singleBurn: boolean;
	/** Plane the departure is flown in, degrees. A launch climbs into the one it
	 *  can reach; an orbit brings its own; a free one is flown as the target's,
	 *  which is what makes it free. Undefined when neither end names a plane. */
	arcIncDeg?: number;
	/** Angle the trip turns between the two planes, degrees. Zero where they
	 *  match, where either is free, and for a landing, which owes none. */
	turnDeg: number;
}

/**
 * Where the arc between two orbits about one body runs, or null when there is
 * no trip in the pair.
 *
 * The arc joins the orbits where they come nearest each other: climbing, it
 * leaves the low side of the departure orbit and meets the other at its high
 * side; coming down, both the other way about. That one rule prices the
 * ordinary cases as they are flown — a low orbit to a stationary one is the
 * Hohmann pair of burns, and a low orbit to a transfer ellipse that already
 * reaches it is the injection alone, with nothing owed on arrival.
 *
 * A landing comes down from wherever the craft already is, so it is never a
 * climb. A flyby of the body you are at is not a trip, and neither is a hop
 * between two points on its ground — that is a suborbital arc, not this one.
 * Nor is meeting another craft: the two ends are then two objects, however
 * close together they are, and the arc between them is a transfer.
 */
export function orbitChangeEnds(
	body: TravelBody,
	options: Pick<
		OrbitChangeOptions,
		'departureMode' | 'arrivalMode' | 'departureOrbit' | 'targetOrbit' | 'departureSiteLatDeg'
	>
): OrbitChangeEnds | null {
	const { departureMode, arrivalMode, departureOrbit, targetOrbit, departureSiteLatDeg } = options;
	if (arrivalMode === 'flyby') return null;
	if (arrivalMode === 'rendezvous' || departureMode === 'rendezvous') return null;
	if (departureMode === 'surface' && arrivalMode === 'landing') return null;

	const from =
		departureMode === 'surface' ? parkingOrbit(body) : (departureOrbit ?? parkingOrbit(body));
	const landingRadius = Math.min(parkingRadiusKm(body), from.rPeriKm);
	const to =
		arrivalMode === 'landing'
			? { rPeriKm: landingRadius, rApoKm: landingRadius }
			: (targetOrbit ?? parkingOrbit(body));
	if (!(from.rPeriKm > 0) || !(to.rPeriKm > 0)) return null;

	// The plane each end is flown in. A launch climbs straight into the target's
	// plane where its latitude reaches it, and into the nearest it can when not;
	// the rest is turned out in the arc. A landing comes down in the plane the
	// craft is already in and owes no turn.
	const latFrom = Math.abs(departureSiteLatDeg ?? 0);
	const fromIncDeg =
		departureMode === 'surface'
			? to.incDeg === undefined
				? undefined
				: Math.min(Math.max(to.incDeg, latFrom), 180 - latFrom)
			: from.incDeg;
	const turnDeg = arrivalMode === 'landing' ? 0 : planeTurnDeg(fromIncDeg, to.incDeg);
	// A free plane is flown as the one it is going to, which is the whole of what
	// makes it free — so the arc lies in the target's wherever it names one.
	const arcIncDeg = fromIncDeg ?? to.incDeg;

	// Which orbit is the bigger of the two, and so which side of each the arc
	// meets. Two orbits in different planes can only be joined where those planes
	// cross, so a turn moves the meeting to a node; without one they meet at the
	// apsis, and the arc's own direction is read back off the two radii.
	const up = to.rApoKm > from.rApoKm || (to.rApoKm === from.rApoKm && to.rPeriKm > from.rPeriKm);
	const atNode = turnDeg > 0;
	const rFromKm = orbitJoinRadiusKm(from, up ? 'periapsis' : 'apoapsis', atNode);
	const rToKm = orbitJoinRadiusKm(to, up ? 'apoapsis' : 'periapsis', atNode);
	const climb = rToKm >= rFromKm;
	const singleBurn = Math.abs(rToKm - rFromKm) < SAME_RADIUS_KM;
	// Two ends at one radius with nothing else to tell them apart is the same
	// place twice, which is not a trip — but two named planes at one radius
	// are, and the trip is the turn between them.
	if (
		singleBurn &&
		departureMode !== 'surface' &&
		arrivalMode !== 'landing' &&
		!(planeTurnDeg(from.incDeg, to.incDeg) > 0)
	)
		return null;
	return { from, to, rFromKm, rToKm, climb, singleBurn, arcIncDeg, turnDeg };
}

/**
 * Build a trip between two orbits about one body.
 *
 * Nothing is escaped and nothing is chased, so there is no Lambert solve and
 * no launch window: the same pair of burns is there on every revolution, and
 * the only choice is how fast to make the crossing between them. Where the two
 * ends name planes, the turn between them is charged at the arc's far end,
 * the slowest point the trip visits.
 */
function buildOrbitChangeRoute(
	body: TravelBody,
	departJd: number,
	tofDays: number,
	options: OrbitChangeOptions
): Route | null {
	const {
		departureMode,
		arrivalMode,
		departureOrbit,
		targetOrbit,
		departureSiteLatDeg,
		targetSiteLatDeg,
		aero
	} = options;
	const ends = orbitChangeEnds(body, options);
	if (!ends) return null;
	const { from, to, rFromKm, rToKm, climb, singleBurn, turnDeg } = ends;
	// The plane the ascent climbs into, which the descent's own tilt is read
	// against. Where the arc lies is the ends' answer, not this builder's.
	const fromIncDeg = ends.arcIncDeg;

	const departureSite =
		departureSiteLatDeg === undefined
			? undefined
			: { latDeg: departureSiteLatDeg, asymptoteTiltDeg: fromIncDeg };
	const targetSite =
		targetSiteLatDeg === undefined
			? undefined
			: { latDeg: targetSiteLatDeg, asymptoteTiltDeg: from.incDeg };
	const legs: RouteLeg[] = [];
	let ascentKms = 0;
	if (departureMode === 'surface') {
		ascentKms = ascentDv(body, departureSite);
		legs.push({ kind: 'ascent', dvKms: ascentKms, days: 0 });
	}

	// What joining the other orbit costs. A climb ends slower than the orbit it
	// meets, so the burn is the difference itself; coming down it ends faster,
	// which is the arrival every other route in the kernel prices — and the only
	// direction an atmosphere can take any of.
	let injectionKms: number;
	let arr: ArrivalCost;
	let inverseAKm: number;

	if (singleBurn) {
		// One burn where the two orbits already cross. What takes time is reaching
		// the point it is made at: half a turn of the orbit the craft is on.
		injectionKms = 0;
		inverseAKm = 2 / (from.rPeriKm + from.rApoKm);
		arr = arrivalCostFromSpeed(
			body,
			orbitSpeedAtRadius(body.mu, from, rToKm),
			arrivalMode,
			aero,
			to,
			targetSite,
			{ deg: turnDeg }
		);
	} else {
		const rNear = Math.min(rFromKm, rToKm);
		const rFar = Math.max(rFromKm, rToKm);
		const arc = solveRadialArc(body.mu, rNear, rFar, tofDays);
		if (!arc) return null;
		inverseAKm = arc.inverseAKm;
		// At the far end the arc carries speed along the radius as well as across
		// the orbit; at the near end it is at periapsis, purely across. The turn
		// between the two planes rides the far burn: the out-of-plane component
		// only touches the across part, and the far end is where it is cheapest.
		const farBurn = (orbit: EndOrbit, farTurnDeg: number) =>
			Math.hypot(
				arc.vFarRadialKms,
				combinedBurn(arc.vFarTangentialKms, orbitSpeedAtRadius(body.mu, orbit, rFar), farTurnDeg)
			);
		if (climb) {
			injectionKms = Math.abs(arc.vNearKms - orbitSpeedAtRadius(body.mu, from, rNear));
			arr = { ...NO_ARRIVAL_COST, captureKms: farBurn(to, turnDeg) };
		} else {
			injectionKms = farBurn(from, turnDeg);
			arr = arrivalCostFromSpeed(body, arc.vNearKms, arrivalMode, aero, to, targetSite);
		}
	}

	legs.push({ kind: 'injection', dvKms: injectionKms, days: 0 });
	const cruiseDays = singleBurn ? orbitPeriodHours(body.mu, from) / 48 : tofDays;
	legs.push({ kind: 'cruise', dvKms: 0, days: cruiseDays });
	legs.push(...arrivalLegs(arr, arrivalMode));

	const totalDvKms = legs.reduce((sum, leg) => sum + leg.dvKms, 0);
	if (!isFinite(totalDvKms)) return null;

	return {
		departureId: body.id,
		targetId: body.id,
		departJd,
		arriveJd: departJd + cruiseDays,
		tofDays: cruiseDays,
		legs,
		totalDvKms,
		inSpaceDvKms: totalDvKms - ascentKms,
		// Bound to the body throughout, so the energy is negative: nothing here is
		// a launch to anywhere a vehicle is rated against.
		c3Km2S2: -body.mu * inverseAKm,
		vInfDepKms: 0,
		vInfArrKms: 0,
		departureMode,
		arrivalMode,
		departureOrbit,
		targetOrbit,
		orbitChange: ends,
		aero,
		entrySpeedKms: arr.entrySpeedKms
	};
}
