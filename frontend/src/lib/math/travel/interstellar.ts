/**
 * Routes between two star systems. A trip runs between the real places of its two
 * ends on its two dates, and no line runs to the centre of a star.
 *
 * A star moves only on the orbits the map draws for its system.
 *
 * The Sun is at the barycentre here. Its offset is about 0.01 au, which moves no
 * price and no date. Only the drawing adds it, because the line must touch the body
 * that the map places.
 *
 * An end in the well of a planet, such as the Moon, takes the place of its planet.
 * The craft coasts through that well with no burn, as on the Δv map.
 *
 * A rapidity figure is the rapidity times c, in km/s. A rocket adds its Δv to this
 * figure, so burns and hyperbolas are priced in it, and it can pass c. At tens of
 * km/s it equals the speed to a rounding error. Every speed on a route is a real
 * speed below c, and {@link speedOfRapidity} alone makes one.
 *
 * A held drive flies a straight relativistic arc at constant proper acceleration.
 * The star wells and the speeds of the bodies stay out of its cost, because they
 * are tens of km/s and the burns are thousands. A stop reaches its end at rest, so
 * it flies no pass through the air.
 *
 * A craft with a Δv budget spends it at departure and coasts on a hyperbola about
 * each star and a straight line between them. The time on all three counts.
 * - The speed of the body at each end sets the cost, so a launch window searches
 *   one orbital period of the body for the date of the fastest coast.
 * - A coast of millennia reaches any date for a small change of speed, so a trip
 *   that stops picks the phase of the least closing speed.
 * - A flyby pays nothing at the meeting, so it keeps its speed and meets the planet
 *   where the planet is.
 * - A planet with no period stays where the map holds it, with the speed of the
 *   orbit that the μ of its star gives at that place.
 * - A launcher has no Δv after the launch, so it only flies by.
 *
 * A low-thrust drive has no route, because its escape is a spiral and this
 * impulsive model cannot show one.
 */

import { clockJd, elementsJd } from '$lib/math/orbit/position';
import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import type { TravelBody } from './body';
import { COAST_SPAN } from './brachistochrone';
import { SEC_PER_DAY, STAR_REACH_KM } from './constants';
import {
	arrivalCost,
	captureDv,
	characteristicEnergy,
	departureCost,
	endArrivalOrbit,
	endDepartureOrbit,
	NO_ARRIVAL_COST,
	periapsisSpeed,
	surfaceSite,
	vInfInside,
	type AeroAssist,
	type ArrivalCost,
	type ArrivalMode,
	type DepartureCost,
	type DepartureMode,
	type EndOrbit
} from './maneuvers';
import { propagateState } from './propagate';
import {
	arrivalLegs,
	finishRoute,
	routeEndJd,
	type ConicSpan,
	type InterstellarCrossing,
	type Route,
	type RouteLeg,
	type RouteOptions
} from './route';
import { elementsToState, type StateVector } from './state';
import {
	add,
	cross,
	dot,
	norm,
	normalize,
	perpendicularTo,
	rotateAbout,
	scale,
	sub,
	type Vec3
} from './vec3';
import { constantThrustAccelMs2, dvWithPayloadKms, isLowThrust, type Vehicle } from './vehicles';

const C_KMS = SPEED_OF_LIGHT_KM_S;

/** The fastest speed a double holds below c, km/s. tanh rounds to 1 past φ ≈ 19. */
const TOP_SPEED_KMS = C_KMS * (1 - Number.EPSILON / 2);

/** The real speed at a rapidity figure, km/s. */
export function speedOfRapidity(rapidityKms: number): number {
	return Math.min(C_KMS * Math.tanh(rapidityKms / C_KMS), TOP_SPEED_KMS);
}

/** The rapidity figure of a real speed, km/s. A price that starts from a speed
 *  on a route reads it through this. */
export function rapidityOfSpeed(speedKms: number): number {
	return C_KMS * Math.atanh(speedKms / C_KMS);
}

/** A well between an end and its star, such as Earth's for the Moon. */
export interface Well {
	/** μ of the body at its centre, km³/s². */
	mu: number;
	/** Radius of the orbit in it that holds the end, or the next well in, km. */
	radiusKm: number;
}

/** One end of a trip between two star systems. */
export interface SystemEnd {
	/** The end as the departure and arrival costs price it. Its elements are
	 *  the orbit about its star of the body that holds its wells, or its own
	 *  when it has none. */
	body: TravelBody;
	/** Position of its star, km, ecliptic J2000 from the solar-system barycentre.
	 *  The Sun is at the barycentre. A star with `starOrbits` turns about this place. */
	starKm: Vec3;
	/** The orbits that carry its star, innermost first, as the map draws them. */
	starOrbits?: readonly OrbitalElements[];
	/** μ of its star, km³/s². Absent when unknown. The period of the orbit then gives it. */
	starMu?: number;
	/** True when the end is the star. It has no orbit about a star then. */
	atStar: boolean;
	/** The wells between the end and its star, the outermost first. Absent for
	 *  an end that goes round its star. */
	wells?: readonly Well[];
}

/** What a craft flies between two systems. */
export type InterstellarDrive =
	/** A held drive at constant proper acceleration, m/s². */
	| { kind: 'torch'; accelMs2: number }
	/** A Δv budget spent in space, km/s. */
	| { kind: 'budget'; dvKms: number }
	/** A launcher: the highest launch energy it reaches with the payload, km²/s². */
	| { kind: 'launch'; c3Km2S2: number };

/** Why a craft has no route between two systems. */
export type InterstellarRefusal =
	| 'no-craft'
	/** Neither a held drive, nor a Δv budget, nor a launch curve. */
	| 'no-drive'
	/** The drive is too weak for a burn. A spiral is not offered between systems. */
	| 'low-thrust'
	/** The Δv does not escape the star of the origin toward the target. */
	| 'cannot-escape'
	/** The Δv escapes, but cannot also stop at the target. */
	| 'cannot-stop';

/** The terms of a route between two systems. Between stars there is no
 *  primary, so the frame terms do not apply. */
export type InterstellarOptions = Omit<RouteOptions, 'centralMu' | 'systemPrimary' | 'orbitChange'>;

export interface InterstellarTorchOptions extends InterstellarOptions {
	/** Where the arc sits between flat out (0) and the longest coast on offer (1). */
	coastFraction?: number;
}

/** The most doublings a bracket on the cruise speed takes. */
const BRACKET_DOUBLINGS = 64;

/** What `vehicle` flies between two systems with `payloadKg` aboard, or why it flies nothing. */
export function interstellarDrive(
	vehicle: Vehicle | null,
	payloadKg: number
): InterstellarDrive | InterstellarRefusal {
	if (!vehicle) return 'no-craft';
	const accelMs2 = constantThrustAccelMs2(vehicle);
	if (accelMs2 !== undefined && accelMs2 > 0) return { kind: 'torch', accelMs2 };
	if (vehicle.kind === 'launcher') {
		const c3Km2S2 = launchEnergyKm2S2(vehicle, payloadKg);
		return c3Km2S2 === null ? 'no-drive' : { kind: 'launch', c3Km2S2 };
	}
	const dvKms = dvWithPayloadKms(vehicle, payloadKg);
	if (dvKms === undefined) return 'no-drive';
	if (isLowThrust(vehicle)) return 'low-thrust';
	return { kind: 'budget', dvKms };
}

/** The highest launch energy at which the curve still lifts `payloadKg`, km²/s².
 *  A payload above the whole curve takes the top of it, so the feasibility
 *  check can say the payload is too heavy. Null without a curve. */
function launchEnergyKm2S2(vehicle: Vehicle, payloadKg: number): number | null {
	const points = vehicle.c3Curve?.points;
	if (!points || points.length === 0) return null;
	let best = points[points.length - 1][0];
	for (let i = 0; i < points.length; i++) {
		const [c3, kg] = points[i];
		if (kg >= payloadKg) continue;
		if (i === 0) break;
		const [c3Before, kgBefore] = points[i - 1];
		best = c3Before + ((c3 - c3Before) * (kgBefore - payloadKg)) / (kgBefore - kg);
		break;
	}
	return best;
}

/**
 * Close the bracket [`lo`, `hi`] on the point where `below` stops being true.
 * It is true at `lo` and false at `hi`. The search stops when the midpoint is
 * an end, because then no double is left between the two ends.
 */
function bisect(lo: number, hi: number, below: (x: number) => boolean): { lo: number; hi: number } {
	for (;;) {
		const mid = (lo + hi) / 2;
		// Written as "not between" so that a NaN also stops it.
		if (!(mid > lo && mid < hi)) return { lo, hi };
		if (below(mid)) lo = mid;
		else hi = mid;
	}
}

/** Mean motion of an end's body about its star, degrees per day. A planet with
 *  no period takes the one that the μ of its star gives. 0 at a star, and when
 *  neither is known. */
function meanMotionOf(end: SystemEnd): number {
	if (end.atStar) return 0;
	const { a, n } = end.body.elements;
	if (n > 0) return n;
	const aKm = a * AU_KM;
	const mu = end.starMu ?? 0;
	return mu > 0 && aKm > 0 ? (Math.sqrt(mu / aKm ** 3) * SEC_PER_DAY * 180) / Math.PI : 0;
}

/** False at a star, and for a planet the map holds at one place. */
function movesOnOrbit(end: SystemEnd): boolean {
	const { n, q } = end.body.elements;
	return !end.atStar && (n > 0 || q != null);
}

/** Place and velocity of an end that is not at its star, as the map draws them.
 *  Null when it has no known motion. The map holds a planet with no period at
 *  its place at the epoch, so that planet has one state on every date. */
function drawnStateAt(end: SystemEnd, jd: number): StateVector | null {
	const { elements } = end.body;
	if (movesOnOrbit(end)) return elementsToState(elements, jd);
	const n = meanMotionOf(end);
	if (!(n > 0)) return null;
	return elementsToState({ ...elements, n }, clockJd(elements, elements.epoch));
}

/** The state of an end about its star at `jd`. A hyperbola about the star reads
 *  its μ, the star's own where it is known. */
export function orbitStateAt(end: SystemEnd, jd: number): StateVector | null {
	if (end.atStar) return null;
	const state = drawnStateAt(end, jd);
	return state && { ...state, mu: end.starMu ?? state.mu };
}

/** Where an end is about its star at `jd`, km. With no motion known, any mean
 *  motion gives the place at the epoch. With no orbit, the end is at its star. */
export function endOffsetKm(end: SystemEnd, jd: number): Vec3 {
	if (end.atStar) return [0, 0, 0];
	const { elements } = end.body;
	const state =
		orbitStateAt(end, jd) ??
		elementsToState({ ...elements, n: 1 }, clockJd(elements, elements.epoch));
	// Not a place: the offset from the star of an end that sits at its star.
	// eslint-disable-next-line no-restricted-syntax
	return state?.r ?? [0, 0, 0];
}

/** Where the star of an end is at `jd`, km, ecliptic J2000 from the solar-system
 *  barycentre. The orbit of a star in a pair moves its place by tens of au, and
 *  its speed there is left out, as a body's is on a held drive. */
export function starPlaceKm(end: SystemEnd, jd: number): Vec3 {
	let place = end.starKm;
	for (const orbit of end.starOrbits ?? []) {
		const state = elementsToState(orbit, jd);
		if (state) place = add(place, state.r);
	}
	return place;
}

/** Where an end is at `jd`, km, ecliptic J2000 from the solar-system barycentre.
 *  This is the place the map gives it. A solar end is about the Sun. */
export function endPlaceKm(end: SystemEnd, jd: number): Vec3 {
	const star = starPlaceKm(end, jd);
	return end.atStar ? star : add(star, endOffsetKm(end, jd));
}

/** `orbit` if the end can hold it. An orbit about a star of unknown μ has no price. */
function orbitAt(end: SystemEnd, orbit: EndOrbit | undefined): EndOrbit | undefined {
	return end.atStar && !end.starMu ? undefined : orbit;
}

/** Least periastron of the orbit that holds station at a star, km. */
const STAR_PASS_KM = AU_KM;

/** Periastron of that orbit at a giant, in radii of the star. It clears the star
 *  by one radius. */
const STAR_PASS_RADII = 2;

/** Periastron of the orbit that holds station at `star`, km. */
function starHoldKm(star: TravelBody): number {
	return Math.max(STAR_PASS_KM, STAR_PASS_RADII * star.radiusKm);
}

/** The part of the gap between two stars that one end can take, so that two ends
 *  never cross. The nearer star has the stronger pull over all of it, up to a mass
 *  ratio of 9. */
const JOIN_SHARE = 1 / 4;

/** Most passes that fix an arrival date against the target's place. Each pass
 *  cuts the error by the ratio of the target's speed to the craft's. */
const ARRIVAL_PASSES = 32;

/** The change in an arrival date that ends those passes, days. */
const ARRIVAL_TOLERANCE_DAYS = 1e-9;

/** The arrival date of a flight whose length depends on that date. */
function settledArrivalJd(departJd: number, flightDays: (arriveJd: number) => number): number {
	let arriveJd = departJd;
	for (let pass = 0; pass < ARRIVAL_PASSES; pass++) {
		const next = departJd + flightDays(arriveJd);
		const change = Math.abs(next - arriveJd);
		arriveJd = next;
		if (change < ARRIVAL_TOLERANCE_DAYS) break;
	}
	return arriveJd;
}

/** The excess against the end itself, for `excessKms` against the body that
 *  holds its wells. Both are rapidity figures. */
function throughWells(end: SystemEnd, excessKms: number): number {
	return (end.wells ?? []).reduce((v, well) => vInfInside(v, well.mu, well.radiusKm), excessKms);
}

/** What a held arc can ask of the air at an end it meets at `excessKms`. A stop
 *  there has no speed left to shed, so no pass is flown or drawn. */
export function crossingAero(aero: AeroAssist, excessKms: number): AeroAssist {
	return excessKms > 0 ? aero : 'none';
}

/** The speed at which a craft meets an atmosphere, as a real speed. */
function entrySpeedOf(cost: ArrivalCost): number | undefined {
	return cost.entrySpeedKms === undefined ? undefined : speedOfRapidity(cost.entrySpeedKms);
}

// --- the held drive ------------------------------------------------------------

/** Rapidity at which a burn from rest covers `distanceKm`. This is
 *  acosh(1 + a·x/c²) in a form that keeps its digits for a short burn. */
function rapidityOver(distanceKm: number, accelKmS2: number): number {
	return 2 * Math.asinh(Math.sqrt((accelKmS2 * distanceKm) / (2 * C_KMS * C_KMS)));
}

/** Distance a burn from rest covers up to rapidity `phi`, km. This is
 *  (c²/a)(cosh φ − 1). */
function burnDistanceKm(phi: number, accelKmS2: number): number {
	return ((2 * C_KMS * C_KMS) / accelKmS2) * Math.sinh(phi / 2) ** 2;
}

/** The rapidity at which `burns` burns and a coast of `coastSeconds` between
 *  them cover `distanceKm`. */
function rapidityWithCoast(
	distanceKm: number,
	accelKmS2: number,
	burns: number,
	coastSeconds: number,
	flatOut: number
): number {
	if (!(coastSeconds > 0)) return flatOut;
	const covered = (phi: number) =>
		burns * burnDistanceKm(phi, accelKmS2) + speedOfRapidity(C_KMS * phi) * coastSeconds;
	return bisect(0, flatOut, (phi) => covered(phi) < distanceKm).hi;
}

/** A relativistic arc over one distance. */
interface HeldFlight {
	/** Rapidity at the end of the boost. */
	phi: number;
	peakKms: number;
	burnSeconds: number;
	burnShipSeconds: number;
	coastSeconds: number;
	/** Earth time of the whole arc. */
	seconds: number;
}

/** The arc of `burns` burns over `distanceKm`, at `share` of the coast span. */
function heldFlight(
	distanceKm: number,
	accelKmS2: number,
	burns: number,
	share: number
): HeldFlight {
	const hold = C_KMS / accelKmS2;
	const flatOut = rapidityOver(distanceKm / burns, accelKmS2);
	const askedSeconds = share * COAST_SPAN * burns * hold * Math.sinh(flatOut);
	const phi = rapidityWithCoast(distanceKm, accelKmS2, burns, askedSeconds, flatOut);
	const peakKms = speedOfRapidity(C_KMS * phi);
	const burnSeconds = hold * Math.sinh(phi);
	const coastSeconds =
		askedSeconds > 0
			? Math.max(0, distanceKm - burns * burnDistanceKm(phi, accelKmS2)) / peakKms
			: 0;
	return {
		phi,
		peakKms,
		burnSeconds,
		burnShipSeconds: hold * phi,
		coastSeconds,
		seconds: burns * burnSeconds + coastSeconds
	};
}

/** What a route echoes that fixes where its crossing runs. */
type CrossingFlight = Pick<
	Route,
	'departJd' | 'arriveJd' | 'departureMode' | 'arrivalMode' | 'departureOrbit' | 'targetOrbit'
>;

/** The straight line of a held arc, km, in the frame of the route. */
export interface HeldLine {
	originKm: Vec3;
	targetKm: Vec3;
	distanceKm: number;
	/** From the place of the origin end to the start of the line. Zero except at a
	 *  star, and kept apart so that a far star keeps every digit. */
	originStandOffKm: Vec3;
	/** From the place of the target end to the end of the line. */
	targetStandOffKm: Vec3;
}

/** Where a held arc stands off the star of `end`, from the star, on the line to
 *  `towardKm`. A close binary leaves it less room than the hold. */
function standOffKm(end: SystemEnd, placeKm: Vec3, towardKm: Vec3): Vec3 {
	const line = sub(towardKm, placeKm);
	return scale(normalize(line), Math.min(starHoldKm(end.body), norm(line) * JOIN_SHARE));
}

/**
 * The line a held arc flies between its two ends. It never reaches the centre of a
 * star. A star with an orbit on the route keeps its place, and the drawing stops
 * the line at the ring. Any other star gives the point of the hold on the side of
 * the other end.
 */
export function heldLine(origin: SystemEnd, target: SystemEnd, flight: CrossingFlight): HeldLine {
	const { departJd, arriveJd, departureMode, arrivalMode, departureOrbit, targetOrbit } = flight;
	const fromKm = endPlaceKm(origin, departJd);
	const toKm = endPlaceKm(target, arriveJd);
	const leavesRing =
		departureOrbit && endDepartureOrbit(origin.body, departureMode, departureOrbit);
	const reachesRing = targetOrbit && endArrivalOrbit(target.body, arrivalMode, targetOrbit);
	const originStandOffKm: Vec3 =
		origin.atStar && !leavesRing ? standOffKm(origin, fromKm, toKm) : [0, 0, 0];
	const targetStandOffKm: Vec3 =
		target.atStar && !reachesRing ? standOffKm(target, toKm, fromKm) : [0, 0, 0];
	const originKm = add(fromKm, originStandOffKm);
	const targetKm = add(toKm, targetStandOffKm);
	return {
		originKm,
		targetKm,
		distanceKm: norm(sub(targetKm, originKm)),
		originStandOffKm,
		targetStandOffKm
	};
}

/**
 * The relativistic arc a held drive flies between two systems.
 *
 * The coast span is measured as inside the solar system. At 1, the coast lasts
 * {@link COAST_SPAN} times as long as the flat-out crossing on the Earth's
 * clock. No geometry ends the span between stars, so 1 always means that coast.
 *
 * Null when the drive pushes nothing, or both ends are in one place.
 */
export function buildInterstellarTorchRoute(
	origin: SystemEnd,
	target: SystemEnd,
	departJd: number,
	accelMs2: number,
	options: InterstellarTorchOptions = {}
): Route | null {
	const {
		departureMode = 'surface',
		arrivalMode = 'capture',
		aero = 'none',
		coastFraction = 0
	} = options;
	const accelKmS2 = accelMs2 / 1000;
	if (!(accelKmS2 > 0)) return null;

	// A flyby keeps its speed, so it never turns round to brake.
	const flips = arrivalMode !== 'flyby';
	const burns = flips ? 2 : 1;
	const share = Math.min(Math.max(coastFraction, 0), 1);
	const departureOrbit = orbitAt(origin, options.departureOrbit);
	const targetOrbit = orbitAt(target, options.targetOrbit);
	const flight = { departJd, departureMode, arrivalMode, departureOrbit, targetOrbit };
	const lineTo = (arriveJd: number) => heldLine(origin, target, { ...flight, arriveJd });
	const arcTo = (jd: number) => heldFlight(lineTo(jd).distanceKm, accelKmS2, burns, share);
	const flownDays = (jd: number) => arcTo(jd).seconds / SEC_PER_DAY;
	const placedJd = settledArrivalJd(departJd, flownDays);
	const { distanceKm } = lineTo(placedJd);
	if (!(distanceKm > 0)) return null;

	const arc = arcTo(placedJd);
	const gamma = Math.cosh(arc.phi);
	const rapidityKms = C_KMS * arc.phi;

	const excessDepKms = throughWells(origin, 0);
	const excessArrKms = throughWells(target, flips ? 0 : rapidityKms);
	const air = crossingAero(aero, excessArrKms);
	const dep = departureCost(
		origin.body,
		excessDepKms,
		departureMode,
		departureOrbit,
		surfaceSite(origin.body, options.departureSiteLatDeg, null)
	);
	const arr = arrivalCost(
		target.body,
		excessArrKms,
		arrivalMode,
		air,
		targetOrbit,
		surfaceSite(target.body, options.targetSiteLatDeg, null)
	);

	// Proper acceleration times proper time, which is c times the rapidity. The
	// rocket equation spends this figure, and it can be more than c.
	const burnDvKms = accelKmS2 * arc.burnShipSeconds;
	const burn = {
		dvKms: burnDvKms,
		days: arc.burnSeconds / SEC_PER_DAY,
		shipDays: arc.burnShipSeconds / SEC_PER_DAY
	};
	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'boost', ...burn });
	if (arc.coastSeconds > 0) {
		legs.push({
			kind: 'cruise',
			dvKms: 0,
			days: arc.coastSeconds / SEC_PER_DAY,
			shipDays: arc.coastSeconds / gamma / SEC_PER_DAY
		});
	}
	if (flips) legs.push({ kind: 'brake', ...burn });
	legs.push(...arrivalLegs(arr, arrivalMode));

	const tofDays = arc.seconds / SEC_PER_DAY;
	return finishRoute(
		{
			departureId: origin.body.id,
			targetId: target.body.id,
			departJd,
			arriveJd: departJd + tofDays,
			tofDays,
			ascentKms: dep.ascentKms,
			c3Km2S2: characteristicEnergy(excessDepKms),
			vInfDepKms: speedOfRapidity(excessDepKms),
			vInfArrKms: speedOfRapidity(excessArrKms),
			departureMode,
			arrivalMode,
			departureOrbit,
			targetOrbit,
			aero,
			entrySpeedKms: entrySpeedOf(arr),
			constantThrust: accelMs2,
			peakSpeedKms: arc.peakKms,
			coastFraction: share,
			interstellar: {
				distanceKm,
				cruiseKms: arc.peakKms,
				gamma,
				rapidityKms
			}
		},
		legs
	);
}

// --- the coast -----------------------------------------------------------------

/** Cruise speeds on the grid that brackets the fastest coast at one date. */
const CRUISE_GRID = 64;

/** The lowest cruise speed on that grid, as a part of one step. */
const GRID_FLOOR = 1e-6;

/** Dates sampled in one orbital period of a body. */
const WINDOW_SAMPLES = 48;

/** Most rounds that solve the speed of a coast and its meeting for each other. */
const MEETING_ROUNDS = 6;

/** The gain in speed that ends those rounds, km/s. */
const SETTLED_KMS = 1e-3;

/** The closest the long way round a star comes to it, as a part of the radius it
 *  starts from. A fast craft can only go that way on a hairpin past the star. */
const LONG_WAY_PASS = 0.01;

/** Halvings of the step that polish a point of a grid. */
const POLISH_PASSES = 24;

/** The part of the craft's limit that a coast keeps back. The feasibility check
 *  adds up the legs in a different order, so a coast at the exact limit can fail
 *  it by a rounding error. */
const LIMIT_MARGIN = 1e-12;

export interface InterstellarCruiseOptions extends InterstellarOptions {
	/** Search one orbital period of the origin's body about its star from the
	 *  departure date for the date of the fastest coast. */
	launchWindow?: boolean;
}

/**
 * Velocity at the unit vector `out` from a star of `mu`, on the hyperbola that
 * turns `sweep` radians about `normal` from there to its outbound asymptote at
 * `speedKms`.
 *
 * With s = √(e² − 1) and k = r·v∞²/μ, the orbit equation at ν = ν∞ − sweep
 * gives s² − k·sin(sweep)·s − k(1 − cos sweep) = 0. The second form of the
 * root keeps its digits when sin(sweep) is negative.
 */
function sweptVelocity(
	out: Vec3,
	normal: Vec3,
	sweep: number,
	rKm: number,
	mu: number,
	speedKms: number
): Vec3 {
	const k = (rKm * speedKms * speedKms) / mu;
	const sinSweep = Math.sin(sweep);
	const versine = 2 * Math.sin(sweep / 2) ** 2;
	const root = Math.sqrt((k * sinSweep) ** 2 + 4 * k * versine);
	const s = sinSweep >= 0 ? (k * sinSweep + root) / 2 : (2 * k * versine) / (root - k * sinSweep);
	const transverse = (s * speedKms) / k;
	const radial = Math.sqrt(Math.max(0, speedKms ** 2 + (2 * mu) / rKm - transverse ** 2));
	// Past the periastron (ν > 0) the craft climbs out. Before it, it falls in.
	const outward = sweep < Math.acos(-1 / Math.sqrt(1 + s * s)) ? 1 : -1;
	return add(scale(out, outward * radial), scale(cross(normal, out), transverse));
}

/** Periapsis of the hyperbola of excess speed `speedKms` through `r` at `v`, km. */
function periapsisKm(r: Vec3, v: Vec3, mu: number, speedKms: number): number {
	const h = norm(cross(r, v));
	const latusKm = (h * h) / mu;
	return latusKm / (1 + Math.sqrt(1 + (latusKm * speedKms ** 2) / mu));
}

/**
 * The velocity at `state` nearest its own that puts a craft on a hyperbola about
 * the star that leaves along `toward` at `speedKms`. The hyperbola lies in the
 * plane of the place and `toward`. It can go round the star either way, unless
 * the long way is a dive at the star.
 */
function departureVelocity(state: StateVector, toward: Vec3, speedKms: number): Vec3 {
	const { r, v, mu } = state;
	const rKm = norm(r);
	const out = scale(r, 1 / rKm);
	const plane = cross(out, toward);
	// On the line of the radius every plane holds the path, so take the body's own.
	const normal = normalize(norm(plane) > 1e-12 ? plane : cross(out, v));
	const angle = Math.atan2(norm(plane), dot(out, toward));
	const one = sweptVelocity(out, normal, angle, rKm, mu, speedKms);
	if (!(angle > 0)) return one;
	const other = sweptVelocity(out, scale(normal, -1), 2 * Math.PI - angle, rKm, mu, speedKms);
	if (norm(sub(one, v)) <= norm(sub(other, v))) return one;
	return periapsisKm(r, other, mu, speedKms) < LONG_WAY_PASS * rKm ? one : other;
}

/** The least excess speed against the body at `state` that leaves along `toward`. */
function departureExcessKms(state: StateVector, toward: Vec3, speedKms: number): number {
	return norm(sub(departureVelocity(state, toward, speedKms), state.v));
}

/** An arrival walked backward is a departure from a body that moves the other way. */
function walkedBack(state: StateVector): StateVector {
	return { ...state, v: scale(state.v, -1) };
}

/** Δv at the periastron between a hyperbola of excess `excessKms` and the orbit
 *  that holds station at `star`, of `mu`. That orbit has the speed of escape
 *  there. It is the limit of the bound orbits, so its burn is the least. */
export function starPassKms(star: TravelBody, mu: number, excessKms: number): number {
	return captureDv(mu, starHoldKm(star), Infinity, excessKms);
}

/** Radius of the pass at the star of `end`, km. */
function starPassRadiusKm(
	end: SystemEnd,
	mode: ArrivalMode | DepartureMode,
	orbit: EndOrbit | undefined
): number {
	return orbit && mode !== 'rendezvous' && mode !== 'flyby' ? orbit.rPeriKm : starHoldKm(end.body);
}

/** Where a coast meets its target. */
interface Meeting {
	/** A date on which the target is there. */
	jd: number;
	placeKm: Vec3;
	/** The closing speed of a coast, as a rapidity figure. `from` is the unit
	 *  vector from the meeting to the origin. */
	closingKms: (from: Vec3, rapidityKms: number) => number;
}

/** The meeting with an end at its place on `jd`, on the hyperbola that comes in
 *  from `from`. With no state known, the coast keeps its whole speed. */
function meetingAt(end: SystemEnd, jd: number): Meeting {
	const state = orbitStateAt(end, jd);
	const back = state && walkedBack(state);
	return {
		jd,
		placeKm: endPlaceKm(end, jd),
		closingKms: (from, kms) => (back ? departureExcessKms(back, from, kms) : kms)
	};
}

/**
 * The meeting at the periastron passage `jd` of a planet, on a hyperbola tangent
 * to its orbit. This closing speed is the difference of the two speeds. No other
 * meeting has a lower one: two velocities differ by at least their speeds, and
 * that difference is least where the well of the star is deepest. So a craft that
 * cannot pay for this meeting cannot pay for any.
 */
function tangentMeeting(end: SystemEnd, jd: number): Meeting {
	const state = orbitStateAt(end, jd);
	return {
		...meetingAt(end, jd),
		closingKms: (_from, kms) =>
			state ? Math.abs(periapsisSpeed(state.mu, norm(state.r), kms) - norm(state.v)) : kms
	};
}

/** The first periastron passage of an end at or after `jd`. Null when it has
 *  none to wait for: a star, a planet the map holds still, or an open orbit. */
function periastronPassageJd(end: SystemEnd, jd: number): number | null {
	if (end.atStar) return null;
	const { elements } = end.body;
	const { e, ma, n, epoch } = elements;
	if (!(n > 0) || !(e < 1)) return null;
	const turns = Math.ceil((ma + n * (elementsJd(elements, jd) - epoch)) / 360);
	return clockJd(elements, epoch + (360 * turns - ma) / n);
}

/** The first date at or after `jd` on which an end has its phase of `phaseJd`. */
function nextPassageJd(end: SystemEnd, phaseJd: number, jd: number): number {
	const periodDays = 360 / end.body.elements.n;
	return phaseJd + Math.ceil((jd - phaseJd) / periodDays) * periodDays;
}

/**
 * The date in one period of a planet from its periastron after `nearJd` of the
 * meeting with the least closing speed, for a coast from `fromKm`. The steps are
 * even in eccentric anomaly, because a long ellipse passes its periastron in a
 * small part of its period.
 */
function bestMeetingJd(
	target: SystemEnd,
	fromKm: Vec3,
	nearJd: number,
	rapidityKms: number
): number {
	const { e, n } = target.body.elements;
	const periastronJd = periastronPassageJd(target, nearJd)!;
	const jdAt = (anomaly: number) =>
		periastronJd + ((anomaly - e * Math.sin(anomaly)) * 180) / Math.PI / n;
	const closingAt = (anomaly: number) => {
		const met = meetingAt(target, jdAt(anomaly));
		return met.closingKms(normalize(sub(fromKm, met.placeKm)), rapidityKms);
	};
	const step = (2 * Math.PI) / WINDOW_SAMPLES;
	const anomalies = Array.from({ length: WINDOW_SAMPLES }, (_, i) => i * step);
	const closings = anomalies.map(closingAt);
	const start = anomalies[closings.indexOf(Math.min(...closings))];
	return jdAt(polish(closingAt, start, step, -Infinity, Infinity));
}

/** How a coast meets the target. */
interface CoastArrival {
	legs: RouteLeg[];
	/** Δv of those legs, km/s. */
	spendKms: number;
	/** Excess against the end itself, as a rapidity figure. */
	excessKms: number;
	cost: ArrivalCost;
}

/**
 * The arrival at `met` from a coast at `rapidityKms`, which comes in from `from`.
 * A trip to a planet meets it at the closing speed of the meeting. A trip to a
 * moon then falls down the planet's well to it. A trip that stops at a star
 * brakes into the orbit it asks for, or else into the orbit that holds station
 * there.
 */
function coastArrival(
	target: SystemEnd,
	met: Meeting,
	from: Vec3,
	rapidityKms: number,
	mode: ArrivalMode,
	options: InterstellarOptions
): CoastArrival {
	if (target.atStar) {
		const cost =
			mode === 'flyby'
				? NO_ARRIVAL_COST
				: options.targetOrbit && mode !== 'rendezvous'
					? arrivalCost(target.body, rapidityKms, mode, 'none', options.targetOrbit)
					: {
							...NO_ARRIVAL_COST,
							captureKms: starPassKms(target.body, target.starMu ?? 0, rapidityKms)
						};
		const legs = arrivalLegs(cost, mode);
		return { legs, spendKms: spendOf(legs), excessKms: rapidityKms, cost };
	}
	const excessKms = throughWells(target, met.closingKms(from, rapidityKms));
	const site = surfaceSite(target.body, options.targetSiteLatDeg, null);
	const cost = arrivalCost(target.body, excessKms, mode, options.aero, options.targetOrbit, site);
	const legs = arrivalLegs(cost, mode);
	return { legs, spendKms: spendOf(legs), excessKms, cost };
}

function spendOf(legs: readonly RouteLeg[]): number {
	return legs.reduce((sum, leg) => sum + leg.dvKms, 0);
}

/** How a coast leaves its origin. */
interface Leaving {
	/** Excess against the origin end itself, as a rapidity figure. */
	excessKms: number;
	cost: DepartureCost;
}

/** How a coast leaves a star: from the orbit it asks for, or else from the
 *  orbit that holds station there. */
function leaveStar(
	star: SystemEnd,
	rapidityKms: number,
	mode: DepartureMode,
	orbit: EndOrbit | undefined
): Leaving {
	const cost =
		orbit && mode === 'orbit'
			? departureCost(star.body, rapidityKms, mode, orbit)
			: {
					ascentKms: 0,
					injectionKms: starPassKms(star.body, star.starMu ?? 0, rapidityKms),
					turnKms: 0,
					turnDeg: 0
				};
	return { excessKms: rapidityKms, cost };
}

/** The fastest coast that leaves at one date. */
interface CoastPlan {
	departJd: number;
	rapidityKms: number;
}

/** What a coast flies to one meeting. */
interface MeetingPlan {
	plan: CoastPlan | InterstellarRefusal;
	met: Meeting;
}

/** A coast as it flies, with its speed fixed by the meeting. */
interface FlownCoast extends CoastPlan {
	arriveJd: number;
}

/** The rapidity figure of a plan, 0 on a refusal. */
function planKms(plan: CoastPlan | InterstellarRefusal): number {
	return typeof plan === 'string' ? 0 : plan.rapidityKms;
}

function faster(a: MeetingPlan, b: MeetingPlan): MeetingPlan {
	return planKms(b.plan) > planKms(a.plan) ? b : a;
}

/** Move `x` toward the least `f` by halving `step` in turn, inside [`min`, `max`].
 *  It never moves more than one step. */
function polish(
	f: (x: number) => number,
	x: number,
	step: number,
	min: number,
	max: number
): number {
	let best = x;
	let least = f(x);
	for (let pass = 0; pass < POLISH_PASSES; pass++) {
		step /= 2;
		for (const next of [best - step, best + step]) {
			const at = Math.min(Math.max(next, min), max);
			const value = f(at);
			if (value < least) {
				best = at;
				least = value;
			}
		}
	}
	return best;
}

/**
 * The highest rapidity figure whose spend stays within `limit`, km/s, or null.
 *
 * The spend can fall before it rises, because a faster hyperbola bends less
 * and can line up better with the body's motion. A grid of figures finds the
 * cheap stretch, and a bisection finds where the spend passes the limit above
 * it.
 */
function fastestWithin(
	spend: (rapidityKms: number) => number,
	limit: number,
	scaleKms: number
): number | null {
	let topKms = 2 * scaleKms + 1;
	for (let i = 0; i < BRACKET_DOUBLINGS && spend(topKms) <= limit; i++) topKms *= 2;
	const step = topKms / CRUISE_GRID;
	const figures = Array.from({ length: CRUISE_GRID + 1 }, (_, i) => step * Math.max(i, GRID_FLOOR));
	const spends = figures.map(spend);
	let last = spends.findLastIndex((value) => value <= limit);
	let lo: number;
	if (last >= 0) lo = figures[last];
	else {
		// A narrow dip under the limit can fall between two figures of the grid.
		last = spends.indexOf(Math.min(...spends));
		lo = polish(spend, figures[last], step, figures[0], topKms);
		if (spend(lo) > limit) return null;
	}
	const hi = figures[Math.min(last + 1, CRUISE_GRID)];
	return bisect(lo, hi, (kms) => spend(kms) <= limit).lo;
}

/** The date in `periodDays` from `fromJd` with the fastest coast. A refusal
 *  when no date has one, `cannot-stop` when some date escapes. */
function bestDate(
	planAt: (jd: number) => CoastPlan | InterstellarRefusal,
	fromJd: number,
	periodDays: number
): CoastPlan | InterstellarRefusal {
	const step = periodDays / WINDOW_SAMPLES;
	let best: CoastPlan | null = null;
	let refusal: InterstellarRefusal = 'cannot-escape';
	for (let i = 0; i < WINDOW_SAMPLES; i++) {
		const plan = planAt(fromJd + i * step);
		if (typeof plan === 'string') {
			if (plan === 'cannot-stop') refusal = plan;
		} else if (!best || plan.rapidityKms > best.rapidityKms) best = plan;
	}
	if (!best) return refusal;
	const slowness = (jd: number) => {
		const plan = planAt(jd);
		return typeof plan === 'string' ? Infinity : -plan.rapidityKms;
	};
	const jd = polish(slowness, best.departJd, step, fromJd, fromJd + periodDays);
	const polished = jd === best.departJd ? best : planAt(jd);
	return typeof polished === 'string' ? best : polished;
}

/** One hyperbola of a coast, seen from its star. */
export interface WellConic {
	/** Place of the star, km, in the frame of the route. */
	starKm: Vec3;
	/** μ of the star, km³/s². */
	mu: number;
	/** The inner end of the hyperbola, km, about the star. This is the body, or
	 *  the periapsis at a star. On the long way round the path goes nearer the
	 *  star from here. */
	r: Vec3;
	/** Velocity at `r`, km/s, on the way to the join. The craft flies a hyperbola
	 *  of arrival in reverse. */
	v: Vec3;
	/** Excess speed of the hyperbola, km/s. */
	speedKms: number;
	/** Time between `r` and the join, s. */
	seconds: number;
	/** Where it meets the line, km, in the frame of the route. */
	joinKm: Vec3;
}

/** The three stretches of a coast. A hyperbola is null when the end has no
 *  star of known μ. The line then runs to the place of the end, or to a stand-off
 *  from a star, as on a held arc. */
export interface CoastShape {
	/** Place of the origin end at departure, km. */
	originKm: Vec3;
	/** Place of the target end at arrival, km. */
	targetKm: Vec3;
	departure: WellConic | null;
	arrival: WellConic | null;
	/** Start of the line, km. */
	lineFromKm: Vec3;
	/** End of the line, km. */
	lineToKm: Vec3;
	/** From the place of the origin end to the start of the line where no hyperbola
	 *  reaches it. See {@link HeldLine}. */
	originStandOffKm: Vec3;
	/** From the place of the target end to the end of the line where no hyperbola
	 *  reaches it. */
	targetStandOffKm: Vec3;
	/** Time on all three stretches, s. */
	seconds: number;
}

/** Radius where a hyperbola from `innerKm` joins the line, km. It stops at
 *  `innerKm` when the gap between the two stars leaves it no room. */
function joinRadiusKm(innerKm: number, gapKm: number): number {
	return Math.max(innerKm, Math.min(Math.max(STAR_REACH_KM, 2 * innerKm), gapKm * JOIN_SHARE));
}

/** A hyperbola, with its time as Kepler's equation gives it. */
export interface Hyperbola {
	/** Semi-major axis, km, as a positive figure. */
	aKm: number;
	e: number;
	/** Semi-latus rectum, km. */
	latusKm: number;
	/** The hyperbolic anomaly at a radius, on the way out. */
	anomalyAt(km: number): number;
	/** Seconds between two hyperbolic anomalies. */
	secondsBetween(fromH: number, toH: number): number;
}

/** The hyperbola through `state` of excess speed `speedKms`. The time needs no
 *  iteration when the radius is known. */
export function hyperbolaThrough(state: StateVector, speedKms: number): Hyperbola {
	const { r, v, mu } = state;
	const aKm = mu / speedKms ** 2;
	const h = cross(r, v);
	const e = Math.sqrt(1 + (dot(h, h) * speedKms ** 2) / mu ** 2);
	const kepler = (H: number) => e * Math.sinh(H) - H;
	return {
		aKm,
		e,
		latusKm: dot(h, h) / mu,
		anomalyAt: (km) => Math.acosh(Math.max(1, (km / aKm + 1) / e)),
		secondsBetween: (fromH, toH) => Math.sqrt(aKm ** 3 / mu) * (kepler(toH) - kepler(fromH))
	};
}

/** Seconds on the hyperbola through `state`, from there out to `toKm`. */
function secondsOut(state: StateVector, speedKms: number, toKm: number): number {
	const { r, v } = state;
	const rKm = norm(r);
	if (!(toKm > rKm)) return 0;
	const { anomalyAt, secondsBetween } = hyperbolaThrough(state, speedKms);
	return secondsBetween(Math.sign(dot(r, v)) * anomalyAt(rKm), anomalyAt(toKm));
}

/** The periapsis at `passKm` of a hyperbola that leaves along `out`. A star has
 *  no plane of its own here, so any plane through `out` serves. */
function starPassState(mu: number, out: Vec3, speedKms: number, passKm: number): StateVector {
	const normal = perpendicularTo(out);
	const e = 1 + (passKm * speedKms ** 2) / mu;
	const inward = rotateAbout(out, normal, -Math.acos(-1 / e));
	const speed = periapsisSpeed(mu, passKm, speedKms);
	return { r: scale(inward, passKm), v: scale(cross(normal, inward), speed), mu };
}

/** The hyperbola between an end and the join. `state` is the end's body, or null. */
function wellConic(
	end: SystemEnd,
	jd: number,
	state: StateVector | null,
	out: Vec3,
	speedKms: number,
	passKm: number,
	gapKm: number
): WellConic | null {
	const leaving = state
		? { ...state, v: departureVelocity(state, out, speedKms) }
		: end.atStar && end.starMu
			? starPassState(end.starMu, out, speedKms, passKm)
			: null;
	if (!leaving) return null;
	const { r, v, mu } = leaving;
	const seconds = secondsOut(leaving, speedKms, joinRadiusKm(norm(r), gapKm));
	const starKm = starPlaceKm(end, jd);
	const joinKm = add(starKm, propagateState(r, v, seconds, mu) ?? r);
	return { starKm, mu, r, v, speedKms, seconds, joinKm };
}

/** The shape of a coast at the real speed `speedKms`. */
function flightShape(
	origin: SystemEnd,
	target: SystemEnd,
	flight: CrossingFlight,
	speedKms: number
): CoastShape {
	const { departJd, arriveJd } = flight;
	const originKm = endPlaceKm(origin, departJd);
	const targetKm = endPlaceKm(target, arriveJd);
	const along = normalize(sub(targetKm, originKm));
	const gapKm = norm(sub(starPlaceKm(target, arriveJd), starPlaceKm(origin, departJd)));
	const conic = (
		end: SystemEnd,
		jd: number,
		state: StateVector | null,
		out: Vec3,
		passKm: number
	) => wellConic(end, jd, state, out, speedKms, passKm, gapKm);

	const departure = conic(
		origin,
		departJd,
		orbitStateAt(origin, departJd),
		along,
		starPassRadiusKm(origin, flight.departureMode, flight.departureOrbit)
	);
	const met = orbitStateAt(target, arriveJd);
	const arrival = conic(
		target,
		arriveJd,
		met && walkedBack(met),
		scale(along, -1),
		starPassRadiusKm(target, flight.arrivalMode, flight.targetOrbit)
	);

	const originStandOffKm: Vec3 =
		origin.atStar && !departure ? standOffKm(origin, originKm, targetKm) : [0, 0, 0];
	const targetStandOffKm: Vec3 =
		target.atStar && !arrival ? standOffKm(target, targetKm, originKm) : [0, 0, 0];
	const lineFromKm = departure?.joinKm ?? add(originKm, originStandOffKm);
	const lineToKm = arrival?.joinKm ?? add(targetKm, targetStandOffKm);
	const seconds =
		(departure?.seconds ?? 0) +
		norm(sub(lineToKm, lineFromKm)) / speedKms +
		(arrival?.seconds ?? 0);
	return {
		originKm,
		targetKm,
		departure,
		arrival,
		lineFromKm,
		lineToKm,
		originStandOffKm,
		targetStandOffKm,
		seconds
	};
}

/** The rapidity figure below `topKms` that flies in `days`. */
function rapidityForDays(flownDays: (kms: number) => number, days: number, topKms: number): number {
	let lo = topKms;
	for (let i = 0; i < BRACKET_DOUBLINGS && flownDays(lo) <= days; i++) lo /= 2;
	return bisect(lo, topKms, (kms) => flownDays(kms) > days).hi;
}

/** Length of the path of a coast, km. A hyperbola counts as its chord. */
function flownKmOf({ departure, arrival, lineFromKm, lineToKm }: CoastShape): number {
	const chordKm = (conic: WellConic | null) =>
		conic ? norm(sub(conic.joinKm, add(conic.starKm, conic.r))) : 0;
	return chordKm(departure) + norm(sub(lineToKm, lineFromKm)) + chordKm(arrival);
}

/** A hyperbola as a route keeps it. A stand-off is a span with no time on it. */
function conicSpan(conic: WellConic | null, placeKm: Vec3, standOff: Vec3): ConicSpan {
	return conic
		? { days: conic.seconds / SEC_PER_DAY, km: norm(sub(conic.joinKm, placeKm)) }
		: { days: 0, km: norm(standOff) };
}

/**
 * The coast between two systems for a craft with a Δv budget or a launch curve.
 *
 * The craft leaves at the highest cruise speed its Δv allows after it keeps back
 * what the arrival needs. A trip that stops then slows just enough to reach the next
 * passage of the best phase. It meets the planet where the planet is when no such
 * speed is in reach, or when the orbit is longer than the trip. The ascent belongs
 * to whatever launched the craft, so the budget does not pay for it.
 *
 * The first search prices the arrival at the tangent meeting, which no meeting
 * beats, so its refusal is final. Then the speed and the phase are solved in
 * turn, because a search of the phases at each speed costs too much.
 *
 * A refusal when the craft cannot escape or cannot stop. Null when the two
 * ends are in one place.
 */
export function buildInterstellarCruiseRoute(
	origin: SystemEnd,
	target: SystemEnd,
	departJd: number,
	drive: Exclude<InterstellarDrive, { kind: 'torch' }>,
	options: InterstellarCruiseOptions = {}
): Route | InterstellarRefusal | null {
	const { departureMode = 'surface', arrivalMode = 'capture', aero = 'none' } = options;
	const passageJd = periastronPassageJd(target, departJd);
	const phased = passageJd !== null;
	const first = phased ? tangentMeeting(target, passageJd) : meetingAt(target, departJd);
	if (!(norm(sub(first.placeKm, endPlaceKm(origin, departJd))) > 0)) return null;
	const stops = arrivalMode !== 'flyby';
	const site = surfaceSite(origin.body, options.departureSiteLatDeg, null);
	const departureOrbit = orbitAt(origin, options.departureOrbit);
	const targetOrbit = orbitAt(target, options.targetOrbit);
	const arrivalOptions = { ...options, targetOrbit };

	/** The way to leave on `jd` for `met`, at any rapidity figure. */
	const leaverAt = (jd: number, met: Meeting) => {
		const state = orbitStateAt(origin, jd);
		const toward = normalize(sub(met.placeKm, endPlaceKm(origin, jd)));
		return (rapidityKms: number): Leaving => {
			if (origin.atStar) return leaveStar(origin, rapidityKms, departureMode, departureOrbit);
			const excessKms = throughWells(
				origin,
				state ? departureExcessKms(state, toward, rapidityKms) : rapidityKms
			);
			const cost = departureCost(origin.body, excessKms, departureMode, departureOrbit, site);
			return { excessKms, cost };
		};
	};
	/** The way to arrive at `met` from a departure on `jd`, at any rapidity figure. */
	const arriverAt = (jd: number, met: Meeting) => {
		const from = normalize(sub(endPlaceKm(origin, jd), met.placeKm));
		return (rapidityKms: number) =>
			coastArrival(target, met, from, rapidityKms, arrivalMode, arrivalOptions);
	};

	// A launcher is held to its excess speed, a craft with a budget to its Δv.
	const launched = drive.kind === 'launch';
	const limit =
		(launched ? Math.sqrt(Math.max(0, drive.c3Km2S2)) : drive.dvKms) * (1 - LIMIT_MARGIN);
	const leaveSpend = ({ excessKms, cost }: Leaving) => (launched ? excessKms : cost.injectionKms);
	const spendOn = (jd: number, met: Meeting) => {
		const leaver = leaverAt(jd, met);
		const arriver = arriverAt(jd, met);
		return (kms: number) => leaveSpend(leaver(kms)) + (launched ? 0 : arriver(kms).spendKms);
	};
	const scaleAt = (jd: number) => {
		const state = orbitStateAt(origin, jd);
		return state ? limit + norm(state.v) : limit;
	};

	const planAt = (jd: number, met: Meeting): CoastPlan | InterstellarRefusal => {
		const scaleKms = scaleAt(jd);
		const rapidityKms = launched && stops ? null : fastestWithin(spendOn(jd, met), limit, scaleKms);
		if (rapidityKms === null) {
			const leaver = leaverAt(jd, met);
			const leaves = (kms: number) => leaveSpend(leaver(kms));
			return fastestWithin(leaves, limit, scaleKms) === null ? 'cannot-escape' : 'cannot-stop';
		}
		return { departJd: jd, rapidityKms };
	};

	const periodDays = origin.atStar ? Infinity : 360 / origin.body.elements.n;
	const windowed = options.launchWindow && Number.isFinite(periodDays);
	const search = (met: Meeting) =>
		windowed ? bestDate((jd) => planAt(jd, met), departJd, periodDays) : planAt(departJd, met);

	/**
	 * The speed of a coast from `jd` and its best meeting, each solved for the
	 * other from the speed `fromKms`. A better meeting costs less at the same
	 * speed, so the speed only rises. A meeting the craft cannot pay for says
	 * little about the speed, so the next round tries half of it.
	 */
	const settled = (jd: number, fromKms: number): MeetingPlan => {
		const fromKm = endPlaceKm(origin, jd);
		const gapKm = norm(sub(starPlaceKm(target, jd), fromKm));
		let kms = fromKms;
		let best: MeetingPlan | null = null;
		for (let round = 0; round < MEETING_ROUNDS; round++) {
			const nearJd = jd + gapKm / speedOfRapidity(kms) / SEC_PER_DAY;
			const met = meetingAt(target, bestMeetingJd(target, fromKm, nearJd, kms));
			const next = { plan: planAt(jd, met), met };
			const gainKms = planKms(next.plan) - (best ? planKms(best.plan) : 0);
			if (gainKms < 0) break;
			best = next;
			if (typeof next.plan === 'string') kms /= 2;
			else if (gainKms < SETTLED_KMS) break;
			else kms = next.plan.rapidityKms;
		}
		return best!;
	};

	/** The speed and the meeting of a coast on the date of a tangent plan. */
	const settledPlan = (tangent: CoastPlan | InterstellarRefusal): MeetingPlan =>
		phased && stops && typeof tangent !== 'string'
			? settled(tangent.departJd, tangent.rapidityKms)
			: { plan: tangent, met: first };

	/** The plan of a window from the tangent plan of its best date. */
	const windowPlan = (tangent: CoastPlan): MeetingPlan => {
		const found = settledPlan(tangent);
		// The tangent price overrates the speed, and the best date moves with it. A
		// flyby pays nothing at the meeting, so its date stands.
		if (!phased || !stops) return found;
		const wider = faster(found, { plan: search(found.met), met: found.met });
		if (typeof wider.plan === 'string') return wider;
		return faster(wider, settled(wider.plan.departJd, wider.plan.rapidityKms));
	};

	const flightFrom = (leaveJd: number) => ({
		departJd: leaveJd,
		departureMode,
		arrivalMode,
		departureOrbit,
		targetOrbit
	});
	const shapeAt = (leaveJd: number, kms: number, jd: number) =>
		flightShape(origin, target, { ...flightFrom(leaveJd), arriveJd: jd }, speedOfRapidity(kms));

	/** The coast that a plan flies. */
	const flownFrom = ({ plan, met }: MeetingPlan): FlownCoast | InterstellarRefusal => {
		if (typeof plan === 'string') return plan;
		const { departJd: leaveJd, rapidityKms: fastestKms } = plan;
		const flownDays = (kms: number, jd: number) => shapeAt(leaveJd, kms, jd).seconds / SEC_PER_DAY;

		/** The coast slowed to the next passage of the phase, or null. */
		const atPassage = () => {
			const earliestJd = leaveJd + flownDays(fastestKms, met.jd);
			const jd = nextPassageJd(target, met.jd, earliestJd);
			if (jd - earliestJd > earliestJd - leaveJd) return null;
			const kms = rapidityForDays((x) => flownDays(x, jd), jd - leaveJd, fastestKms);
			return spendOn(leaveJd, meetingAt(target, jd))(kms) <= limit
				? { rapidityKms: kms, arriveJd: jd }
				: null;
		};
		const arrivalAt = (kms: number) => settledArrivalJd(leaveJd, (jd) => flownDays(kms, jd));
		/** The coast that meets the target at its real place on the date it gets there, or null. */
		const whereItIs = () => {
			const spendThere = (kms: number) => spendOn(leaveJd, meetingAt(target, arrivalAt(kms)))(kms);
			const kms = movesOnOrbit(target)
				? fastestWithin(spendThere, limit, scaleAt(leaveJd))
				: fastestKms;
			return kms === null ? null : { rapidityKms: kms, arriveJd: arrivalAt(kms) };
		};
		/** {@link whereItIs} for a flyby, whose meeting only turns its line a little.
		 *  So the speed and the date are solved in turn, which saves a settled date on
		 *  each step of the search. The same date twice keeps the coast in its limit. */
		const flyingBy = () => {
			let jd = arrivalAt(fastestKms);
			for (let round = 0; movesOnOrbit(target) && round < MEETING_ROUNDS; round++) {
				const kms = fastestWithin(spendOn(leaveJd, meetingAt(target, jd)), limit, scaleAt(leaveJd));
				if (kms === null) break;
				const next = arrivalAt(kms);
				if (next === jd) return { rapidityKms: kms, arriveJd: jd };
				jd = next;
			}
			return whereItIs();
		};

		// A flyby pays nothing at the meeting, so no phase is worth a slower coast.
		const flown = stops ? ((phased ? atPassage() : null) ?? whereItIs()) : flyingBy();
		if (!flown) return stops ? 'cannot-stop' : 'cannot-escape';
		return { departJd: leaveJd, ...flown };
	};

	/** The fastest coast on offer. The window ranks its dates before the meeting
	 *  slows them, so the first date can still beat the date it picks. */
	const fastestCoast = (tangent: CoastPlan): FlownCoast | InterstellarRefusal => {
		if (!windowed) return flownFrom(settledPlan(tangent));
		const picked = flownFrom(windowPlan(tangent));
		const onFirstDate = flownFrom(settledPlan(planAt(departJd, first)));
		return planKms(onFirstDate) > planKms(picked) ? onFirstDate : picked;
	};

	const firstPlan = search(first);
	if (typeof firstPlan === 'string') return firstPlan;
	const coast = fastestCoast(firstPlan);
	if (typeof coast === 'string') return coast;
	const { departJd: leaveJd, rapidityKms, arriveJd } = coast;

	const meeting = meetingAt(target, arriveJd);
	const leaving = leaverAt(leaveJd, meeting)(rapidityKms);
	const arrival = arriverAt(leaveJd, meeting)(rapidityKms);
	const shape = shapeAt(leaveJd, rapidityKms, arriveJd);
	const { originKm, targetKm } = shape;
	const dep = leaving.cost;
	const gamma = Math.cosh(rapidityKms / C_KMS);
	const tofDays = arriveJd - leaveJd;

	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'cruise', dvKms: 0, days: tofDays, shipDays: tofDays / gamma });
	legs.push(...arrival.legs);

	return finishRoute(
		{
			departureId: origin.body.id,
			targetId: target.body.id,
			departJd: leaveJd,
			arriveJd,
			tofDays,
			ascentKms: dep.ascentKms,
			c3Km2S2: characteristicEnergy(leaving.excessKms),
			vInfDepKms: speedOfRapidity(leaving.excessKms),
			vInfArrKms: speedOfRapidity(arrival.excessKms),
			departureMode,
			arrivalMode,
			departureOrbit,
			targetOrbit,
			aero,
			entrySpeedKms: entrySpeedOf(arrival.cost),
			interstellar: {
				distanceKm: norm(sub(targetKm, originKm)),
				cruiseKms: speedOfRapidity(rapidityKms),
				gamma,
				rapidityKms,
				conics: {
					departure: conicSpan(shape.departure, originKm, shape.originStandOffKm),
					arrival: conicSpan(shape.arrival, targetKm, shape.targetStandOffKm),
					flownKm: flownKmOf(shape)
				}
			}
		},
		legs
	);
}

/** The stretches of a coast, rebuilt from its route and its two ends. Null on a
 *  held arc, and on any other route. */
export function coastShape(route: Route, origin: SystemEnd, target: SystemEnd): CoastShape | null {
	const crossing = route.interstellar;
	return crossing?.conics ? flightShape(origin, target, route, crossing.cruiseKms) : null;
}

/** Where a hyperbola is `seconds` on from its inner end, km, in the frame of the
 *  route. */
export function conicPlaceKm(conic: WellConic, seconds: number): Vec3 {
	return add(conic.starKm, propagateState(conic.r, conic.v, seconds, conic.mu) ?? conic.r);
}

/**
 * When the fastest route that `drive` flies between two systems from
 * `departJd` is over, JD. That is the flat-out arc of a held drive, or the
 * coast on the date that `options` give it. No route of the drive is over
 * sooner, so an earlier deadline admits none. Null when the drive flies no
 * route.
 */
export function fastestCrossingEndJd(
	origin: SystemEnd,
	target: SystemEnd,
	departJd: number,
	drive: InterstellarDrive,
	options: InterstellarCruiseOptions = {}
): number | null {
	const route =
		drive.kind === 'torch'
			? buildInterstellarTorchRoute(origin, target, departJd, drive.accelMs2, options)
			: buildInterstellarCruiseRoute(origin, target, departJd, drive, options);
	return route !== null && typeof route !== 'string' ? routeEndJd(route) : null;
}

// --- reading a crossing back -----------------------------------------------------

/** The held arc of a route between two systems, read back from its legs. */
interface HeldArc {
	accelKmS2: number;
	/** Rapidity at the end of the boost. */
	phi: number;
	/** 2 with a brake, 1 on a flyby. */
	burns: number;
	/** Length of one burn, km. */
	burnKm: number;
	/** Distance from the origin end where the coast ends, km. */
	coastEndKm: number;
}

/** Null on a coast. */
function heldArcOf(route: Route, totalKm: number): HeldArc | null {
	const boost = route.legs.find((leg) => leg.kind === 'boost');
	if (route.constantThrust === undefined || !boost) return null;
	const accelKmS2 = route.constantThrust / 1000;
	const phi = (accelKmS2 * (boost.shipDays ?? boost.days) * SEC_PER_DAY) / C_KMS;
	const burns = route.legs.some((leg) => leg.kind === 'brake') ? 2 : 1;
	const burnKm = Math.min(burnDistanceKm(phi, accelKmS2), totalKm / burns);
	return { accelKmS2, phi, burns, burnKm, coastEndKm: totalKm - (burns - 1) * burnKm };
}

/** A stretch of a crossing between two systems. */
export interface CrossingStretch {
	kind: 'boost' | 'cruise' | 'brake';
	/** Distance along the crossing from the origin end at which it starts, km. */
	fromKm: number;
	/** Distance along the crossing from the origin end at which it ends, km. */
	toKm: number;
}

/**
 * The stretches of a crossing between two systems, in flight order, one for
 * each leg of the crossing. A coast is one stretch, whatever its shape: see
 * {@link coastShape}. A held drive has a boost, a cruise when it coasts, and a
 * brake when it stops. Null on any other route.
 */
export function crossingStretches(route: Route): CrossingStretch[] | null {
	const crossing = route.interstellar;
	if (!crossing) return null;
	const totalKm = crossing.distanceKm;
	const held = heldArcOf(route, totalKm);
	const stretches: CrossingStretch[] = [];
	let at = 0;
	for (const leg of route.legs) {
		if (leg.kind !== 'boost' && leg.kind !== 'cruise' && leg.kind !== 'brake') continue;
		const lengthKm = !held
			? totalKm
			: leg.kind === 'cruise'
				? held.coastEndKm - held.burnKm
				: held.burnKm;
		stretches.push({ kind: leg.kind, fromKm: at, toKm: at + lengthKm });
		at += lengthKm;
	}
	// The last stretch ends at the target, whatever the rounding.
	if (stretches.length > 0) stretches[stretches.length - 1].toKm = totalKm;
	return stretches;
}

/** Time from departure until a coast is `x` km along its crossing, s. The pace
 *  on a hyperbola is even here, because it is a tiny part of the crossing. A ring
 *  wider than the gap between the ends leaves the line no room between the spans,
 *  so the pace is then even on the whole crossing. */
function coastSecondsAt(route: Route, x: number): number {
	const { distanceKm, conics } = route.interstellar!;
	const { departure, arrival } = conics!;
	const tofSeconds = route.tofDays * SEC_PER_DAY;
	const lineKm = distanceKm - departure.km - arrival.km;
	if (!(lineKm > 0)) return (x / distanceKm) * tofSeconds;
	const outSeconds = departure.days * SEC_PER_DAY;
	const inSeconds = arrival.days * SEC_PER_DAY;
	if (x < departure.km) return (x / departure.km) * outSeconds;
	if (x > distanceKm - arrival.km) {
		return tofSeconds - ((distanceKm - x) / arrival.km) * inSeconds;
	}
	const lineSeconds = tofSeconds - outSeconds - inSeconds;
	return outSeconds + ((x - departure.km) / lineKm) * lineSeconds;
}

/** Time from departure until the craft is `distanceKm` along a route between
 *  two systems from its origin end, days, on the Earth's clock and on the
 *  ship's. Null on any other route. */
export function crossingElapsed(
	route: Route,
	distanceKm: number
): { days: number; shipDays: number } | null {
	const crossing = route.interstellar;
	if (!crossing) return null;
	const totalKm = crossing.distanceKm;
	const x = Math.min(Math.max(distanceKm, 0), totalKm);
	const done = (seconds: number, shipSeconds: number) => ({
		days: seconds / SEC_PER_DAY,
		shipDays: shipSeconds / SEC_PER_DAY
	});

	const arc = heldArcOf(route, totalKm);
	if (!arc) {
		const seconds = coastSecondsAt(route, x);
		return done(seconds, seconds / crossing.gamma);
	}

	const { accelKmS2, phi, burnKm, coastEndKm } = arc;
	const hold = C_KMS / accelKmS2;
	const speedKms = speedOfRapidity(C_KMS * phi);
	const gamma = Math.cosh(phi);
	const burnFor = (km: number) => {
		const p = rapidityOver(km, accelKmS2);
		return { seconds: hold * Math.sinh(p), shipSeconds: hold * p };
	};

	if (x <= burnKm) {
		const along = burnFor(x);
		return done(along.seconds, along.shipSeconds);
	}
	const burn = { seconds: hold * Math.sinh(phi), shipSeconds: hold * phi };
	const coastTo = (km: number) => (km - burnKm) / speedKms;
	if (x <= coastEndKm) {
		return done(burn.seconds + coastTo(x), burn.shipSeconds + coastTo(x) / gamma);
	}
	// The brake mirrors the boost, read back from the end of the crossing.
	const rest = burnFor(totalKm - x);
	const coast = coastTo(coastEndKm);
	return done(
		2 * burn.seconds + coast - rest.seconds,
		2 * burn.shipSeconds + coast / gamma - rest.shipSeconds
	);
}

/** Length of the path a craft flies over a crossing, km. */
export function crossingFlownKm(crossing: InterstellarCrossing): number {
	return crossing.conics?.flownKm ?? crossing.distanceKm;
}

/** How a crossing meets the matter at rest along it. */
export interface CrossingSweep {
	/** Distance from the origin end where the craft first has its peak speed, km. */
	peakAtKm: number;
	/** γ − 1 at the peak speed. */
	peakExcess: number;
	/** The integral of γ − 1 along the crossing, km. Matter at rest hits the
	 *  craft with (γ − 1)c² per kg, so this times its mass per volume and c² is
	 *  the energy that hits one area. */
	excessKm: number;
}

/** Null on any route other than a crossing between two systems. */
export function crossingSweep(route: Route): CrossingSweep | null {
	const crossing = route.interstellar;
	if (!crossing) return null;
	const arc = heldArcOf(route, crossing.distanceKm);
	if (!arc) {
		const peakExcess = lorentzExcess(crossing.rapidityKms / C_KMS);
		return { peakAtKm: 0, peakExcess, excessKm: peakExcess * crossingFlownKm(crossing) };
	}
	const peakExcess = lorentzExcess(arc.phi);
	// Over a burn from rest the integral is (c²/a)(cosh φ − 1)²/2.
	const burnExcessKm = ((C_KMS * C_KMS) / arc.accelKmS2) * (peakExcess ** 2 / 2);
	return {
		peakAtKm: arc.burnKm,
		peakExcess,
		excessKm: arc.burns * burnExcessKm + peakExcess * (arc.coastEndKm - arc.burnKm)
	};
}

/** γ − 1 at rapidity `phi`, in a form that keeps its digits at low speed. */
function lorentzExcess(phi: number): number {
	return 2 * Math.sinh(phi / 2) ** 2;
}

/** A rate per ship second that depends only on the rapidity φ of the craft. */
export interface RapidityRate {
	/** The rate at φ. */
	at(phi: number): number;
	/** The integral of the rate over the rapidity from rest to φ. Times c/a, it is
	 *  the total over a burn from rest to φ, because the ship time there is (c/a) dφ. */
	fromRest(phi: number): number;
}

/**
 * The total of `rate` over the ship time of a crossing between two systems,
 * from `fromKm` to `toKm` along it from the origin end. Null on any other route.
 */
export function crossingIntegral(
	route: Route,
	rate: RapidityRate,
	fromKm = 0,
	toKm = Infinity
): number | null {
	const crossing = route.interstellar;
	if (!crossing) return null;
	const totalKm = crossing.distanceKm;
	const lo = Math.min(Math.max(fromKm, 0), totalKm);
	const hi = Math.min(Math.max(toKm, lo), totalKm);
	// A coast of x takes x / (c sinh φ) of ship time.
	const coast = (phi: number, km: number) => (rate.at(phi) * km) / (C_KMS * Math.sinh(phi));

	const arc = heldArcOf(route, totalKm);
	if (!arc) {
		// The time in a well is not in proportion to its length.
		const seconds = coastSecondsAt(route, hi) - coastSecondsAt(route, lo);
		return (rate.at(crossing.rapidityKms / C_KMS) * seconds) / crossing.gamma;
	}

	const { accelKmS2, phi, burnKm, coastEndKm } = arc;
	// Each distance is from the end where the burn is at rest. The brake ends at the target.
	const burn = (nearKm: number, farKm: number) =>
		(C_KMS / accelKmS2) *
		(rate.fromRest(rapidityOver(farKm, accelKmS2)) -
			rate.fromRest(rapidityOver(nearKm, accelKmS2)));
	let total = 0;
	if (lo < burnKm) total += burn(lo, Math.min(hi, burnKm));
	const coastKm = Math.min(hi, coastEndKm) - Math.max(lo, burnKm);
	if (coastKm > 0) total += coast(phi, coastKm);
	if (hi > coastEndKm) total += burn(totalKm - hi, totalKm - Math.max(lo, coastEndKm));
	return total;
}
