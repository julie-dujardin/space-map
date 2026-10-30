/**
 * Routes between two star systems.
 *
 * The stars do not move, so the crossing is the straight line between them.
 * The time spent in the wells of the two stars is left out.
 *
 * An end in the well of a planet, such as the Moon, is at the place of its
 * planet about the star. Below, "the body" of such an end is that planet. The
 * craft leaves the moon and then coasts out of the planet's well with no burn,
 * as on the Δv map. An arrival at a moon is the same in reverse.
 *
 * A craft with a held drive flies a relativistic arc at constant proper
 * acceleration. To stop, it burns, coasts and burns again. For a flyby, it
 * burns and coasts. Ship time and Earth time differ on this arc. Each end uses
 * the departure and arrival costs of every other route. The star wells and the
 * speeds of the bodies about their stars are left out of its cost. They are
 * tens of km/s, and the burns are thousands.
 *
 * A craft with a Δv budget spends it at departure and coasts. A trip that
 * stops keeps back the Δv to brake.
 * - The departure is a hyperbola about the origin's star that passes the body
 *   and leaves toward the target star. The craft leaves the body at the excess
 *   speed that puts it on that hyperbola, so the body's place and velocity at
 *   the date set the cost. A launch window searches one orbital period of the
 *   body for the date of the fastest coast.
 * - A planet with no period moves at the mean motion that the μ of its star
 *   gives.
 * - The arrival at a planet is a hyperbola about its star with the periastron
 *   at the periastron of the planet. The craft meets the planet there and pays
 *   the capture costs of the planet. The approach lies in the plane of the
 *   planet's orbit.
 * - A craft that holds station at a star is on the orbit with the periastron
 *   at 1 au and the speed of escape there. It brakes into that orbit at the
 *   periastron, and leaves from there.
 *
 * A launcher has no Δv after the launch, so it only flies by. It uses the
 * highest launch energy its curve gives with the payload.
 *
 * No route for a low-thrust drive: its escape is a spiral, which this
 * impulsive model cannot show. No route for a craft with neither a held drive
 * nor a Δv budget, or when no craft is picked.
 */

import { AU_KM, SPEED_OF_LIGHT_KM_S } from '$lib/math/units';
import { muFromElements, type TravelBody } from './body';
import { COAST_SPAN } from './brachistochrone';
import { SEC_PER_DAY } from './constants';
import {
	arrivalCost,
	captureDv,
	characteristicEnergy,
	departureCost,
	NO_ARRIVAL_COST,
	periapsisSpeed,
	surfaceSite,
	vInfInside,
	type ArrivalCost,
	type ArrivalMode,
	type DepartureCost
} from './maneuvers';
import {
	arrivalLegs,
	finishRoute,
	routeEndJd,
	type Route,
	type RouteLeg,
	type RouteOptions
} from './route';
import { elementsToState, type StateVector } from './state';
import { add, cross, dot, norm, normalize, scale, sub, type Vec3 } from './vec3';
import { constantThrustAccelMs2, dvWithPayloadKms, isLowThrust, type Vehicle } from './vehicles';

const C_KMS = SPEED_OF_LIGHT_KM_S;

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
	/** Position of its star, km, ecliptic J2000 from the solar-system barycentre. */
	starKm: Vec3;
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

/** Distance between the two stars, km. */
function starDistanceKm(origin: SystemEnd, target: SystemEnd): number {
	return norm(sub(target.starKm, origin.starKm));
}

/** Excess speed against the end itself, for `vInfKms` against the body that
 *  holds its wells. */
function throughWells(end: SystemEnd, vInfKms: number): number {
	return (end.wells ?? []).reduce((v, well) => vInfInside(v, well.mu, well.radiusKm), vInfKms);
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
		burns * burnDistanceKm(phi, accelKmS2) + C_KMS * Math.tanh(phi) * coastSeconds;
	return bisect(0, flatOut, (phi) => covered(phi) < distanceKm).hi;
}

/**
 * The relativistic arc a held drive flies between two systems.
 *
 * The coast span is measured as inside the solar system. At 1, the coast lasts
 * {@link COAST_SPAN} times as long as the flat-out crossing on the Earth's
 * clock. No geometry ends the span between stars, so 1 always means that coast.
 *
 * Null when the drive pushes nothing, or both stars are in one place.
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
	const distanceKm = starDistanceKm(origin, target);
	if (!(accelKmS2 > 0) || !(distanceKm > 0)) return null;

	// A flyby keeps its speed, so it never turns round to brake.
	const flips = arrivalMode !== 'flyby';
	const burns = flips ? 2 : 1;
	const hold = C_KMS / accelKmS2;
	const flatOut = rapidityOver(distanceKm / burns, accelKmS2);
	const share = Math.min(Math.max(coastFraction, 0), 1);
	const askedSeconds = share * COAST_SPAN * burns * hold * Math.sinh(flatOut);
	const phi = rapidityWithCoast(distanceKm, accelKmS2, burns, askedSeconds, flatOut);

	const peakKms = C_KMS * Math.tanh(phi);
	const gamma = Math.cosh(phi);
	const burnSeconds = hold * Math.sinh(phi);
	const burnShipSeconds = hold * phi;
	const coastSeconds =
		askedSeconds > 0
			? Math.max(0, distanceKm - burns * burnDistanceKm(phi, accelKmS2)) / peakKms
			: 0;

	const vInfDepKms = throughWells(origin, 0);
	const vInfArrKms = throughWells(target, flips ? 0 : peakKms);
	const dep = departureCost(
		origin.body,
		vInfDepKms,
		departureMode,
		options.departureOrbit,
		surfaceSite(origin.body, options.departureSiteLatDeg, null)
	);
	const arr = arrivalCost(
		target.body,
		vInfArrKms,
		arrivalMode,
		aero,
		options.targetOrbit,
		surfaceSite(target.body, options.targetSiteLatDeg, null)
	);

	// Proper acceleration times proper time, which is c times the rapidity. The
	// rocket equation spends this figure, and it can be more than c.
	const burnDvKms = accelKmS2 * burnShipSeconds;
	const burn = {
		dvKms: burnDvKms,
		days: burnSeconds / SEC_PER_DAY,
		shipDays: burnShipSeconds / SEC_PER_DAY
	};
	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'boost', ...burn });
	if (coastSeconds > 0) {
		legs.push({
			kind: 'cruise',
			dvKms: 0,
			days: coastSeconds / SEC_PER_DAY,
			shipDays: coastSeconds / gamma / SEC_PER_DAY
		});
	}
	if (flips) legs.push({ kind: 'brake', ...burn });
	legs.push(...arrivalLegs(arr, arrivalMode));

	const tofDays = (burns * burnSeconds + coastSeconds) / SEC_PER_DAY;
	return finishRoute(
		{
			departureId: origin.body.id,
			targetId: target.body.id,
			departJd,
			arriveJd: departJd + tofDays,
			tofDays,
			ascentKms: dep.ascentKms,
			c3Km2S2: characteristicEnergy(vInfDepKms),
			vInfDepKms,
			vInfArrKms,
			departureMode,
			arrivalMode,
			departureOrbit: options.departureOrbit,
			targetOrbit: options.targetOrbit,
			aero,
			entrySpeedKms: arr.entrySpeedKms,
			constantThrust: accelMs2,
			peakSpeedKms: peakKms,
			coastFraction: share,
			interstellar: { distanceKm, cruiseKms: peakKms, gamma }
		},
		legs
	);
}

// --- the coast -----------------------------------------------------------------

/** Periastron of the orbit that holds station at a star, km. */
const STAR_PASS_KM = AU_KM;

/** Cruise speeds on the grid that brackets the fastest coast at one date. */
const CRUISE_GRID = 64;

/** The lowest cruise speed on that grid, as a part of one step. */
const GRID_FLOOR = 1e-6;

/** Departure dates sampled in one orbital period of the origin body. */
const WINDOW_SAMPLES = 48;

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

/** Place and velocity of an end about its star at `jd`. Null when it has no motion. */
function orbitStateAt(end: SystemEnd, jd: number): StateVector | null {
	const n = meanMotionOf(end);
	return n > 0 ? elementsToState({ ...end.body.elements, n }, jd, end.starMu) : null;
}

/**
 * Velocity at the unit vector `out` from a star of `mu`, on the hyperbola that
 * turns `sweep` radians about `normal` from there to its outbound asymptote at
 * `cruiseKms`.
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
	cruiseKms: number
): Vec3 {
	const k = (rKm * cruiseKms * cruiseKms) / mu;
	const sinSweep = Math.sin(sweep);
	const versine = 2 * Math.sin(sweep / 2) ** 2;
	const root = Math.sqrt((k * sinSweep) ** 2 + 4 * k * versine);
	const s = sinSweep >= 0 ? (k * sinSweep + root) / 2 : (2 * k * versine) / (root - k * sinSweep);
	const transverse = (s * cruiseKms) / k;
	const radial = Math.sqrt(Math.max(0, cruiseKms ** 2 + (2 * mu) / rKm - transverse ** 2));
	// Past the periastron (ν > 0) the craft climbs out. Before it, it falls in.
	const outward = sweep < Math.acos(-1 / Math.sqrt(1 + s * s)) ? 1 : -1;
	return add(scale(out, outward * radial), scale(cross(normal, out), transverse));
}

/**
 * The least excess speed against the body at `state` that puts the craft on a
 * hyperbola about its star that leaves along `toward` at `cruiseKms`. The
 * hyperbola lies in the plane of the body's place and `toward`, and it can go
 * round the star either way.
 */
function departureExcessKms(state: StateVector, toward: Vec3, cruiseKms: number): number {
	const { r, v, mu } = state;
	const rKm = norm(r);
	const out = scale(r, 1 / rKm);
	const plane = cross(out, toward);
	// On the line of the radius every plane holds the path, so take the body's own.
	const normal = normalize(norm(plane) > 1e-12 ? plane : cross(out, v));
	const angle = Math.atan2(norm(plane), dot(out, toward));
	const excess = (n: Vec3, sweep: number) =>
		norm(sub(sweptVelocity(out, n, sweep, rKm, mu, cruiseKms), v));
	const one = excess(normal, angle);
	return angle > 0 ? Math.min(one, excess(scale(normal, -1), 2 * Math.PI - angle)) : one;
}

/** Δv at the periastron between a hyperbola of excess speed `vInfKms` and the
 *  orbit that holds station at a star of `mu`. That orbit has the speed of
 *  escape there. It is the limit of the bound orbits, so its burn is the least. */
function starPassKms(mu: number, vInfKms: number): number {
	return captureDv(mu, STAR_PASS_KM, Infinity, vInfKms);
}

/** Where a coast meets a planet. */
interface Periastron {
	rKm: number;
	/** Speed of the planet there, km/s. */
	speedKms: number;
	/** μ of the star, km³/s². */
	mu: number;
}

/**
 * The periastron of a planet's orbit, or null at a star. A coast of millennia
 * meets the planet at any point of its orbit for a tiny change of the
 * departure date. The periastron is the cheapest point, where the well of the
 * star is deepest and the planet is fastest.
 */
function periastronOf(end: SystemEnd): Periastron | null {
	if (end.atStar) return null;
	const { elements } = end.body;
	const rKm = elements.a * (1 - elements.e) * AU_KM;
	if (!(rKm > 0)) return null;
	const mu = end.starMu ?? (elements.n > 0 ? muFromElements(elements) : 0);
	return { rKm, speedKms: Math.sqrt((mu * (1 + elements.e)) / rKm), mu };
}

/** How a coast meets the target. */
interface CoastArrival {
	legs: RouteLeg[];
	/** Δv of those legs, km/s. */
	spendKms: number;
	/** Speed against the end itself, km/s. */
	vInfKms: number;
	cost: ArrivalCost;
}

/**
 * The arrival from a coast at `cruiseKms`. A trip to a planet falls in to the
 * periastron of the planet and meets the planet there at the difference of
 * the two speeds. A trip to a moon then falls down the planet's well to it. A
 * trip that stops at a star brakes into the orbit that holds station there.
 */
function coastArrival(
	target: SystemEnd,
	cruiseKms: number,
	mode: ArrivalMode,
	options: InterstellarOptions
): CoastArrival {
	const at = periastronOf(target);
	if (!at) {
		const cost =
			mode === 'flyby'
				? NO_ARRIVAL_COST
				: { ...NO_ARRIVAL_COST, captureKms: starPassKms(target.starMu ?? 0, cruiseKms) };
		const legs = arrivalLegs(cost, mode);
		return { legs, spendKms: spendOf(legs), vInfKms: cruiseKms, cost };
	}
	const vInfKms = throughWells(target, periapsisSpeed(at.mu, at.rKm, cruiseKms) - at.speedKms);
	const site = surfaceSite(target.body, options.targetSiteLatDeg, null);
	const cost = arrivalCost(target.body, vInfKms, mode, options.aero, options.targetOrbit, site);
	const legs = arrivalLegs(cost, mode);
	return { legs, spendKms: spendOf(legs), vInfKms, cost };
}

function spendOf(legs: readonly RouteLeg[]): number {
	return legs.reduce((sum, leg) => sum + leg.dvKms, 0);
}

/** How a coast leaves its origin. */
interface Leaving {
	/** Excess speed against the origin end itself, km/s. */
	vInfKms: number;
	cost: DepartureCost;
}

/** The fastest coast that leaves at one date. */
interface CoastPlan {
	departJd: number;
	/** Classical speed on the coast, km/s. This is c times the rapidity. */
	cruiseKms: number;
	leaving: Leaving;
	arrival: CoastArrival;
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
 * The highest cruise speed whose spend stays within `limit`, km/s, or null.
 *
 * The spend can fall before it rises, because a faster hyperbola bends less
 * and can line up better with the body's motion. A grid of speeds finds the
 * cheap stretch, and a bisection finds where the spend passes the limit above
 * it.
 */
function fastestWithin(
	spend: (kms: number) => number,
	limit: number,
	scaleKms: number
): number | null {
	let topKms = 2 * scaleKms + 1;
	for (let i = 0; i < BRACKET_DOUBLINGS && spend(topKms) <= limit; i++) topKms *= 2;
	const step = topKms / CRUISE_GRID;
	const speeds = Array.from({ length: CRUISE_GRID + 1 }, (_, i) => step * Math.max(i, GRID_FLOOR));
	const spends = speeds.map(spend);
	let last = spends.findLastIndex((value) => value <= limit);
	let lo: number;
	if (last >= 0) lo = speeds[last];
	else {
		// A narrow dip under the limit can fall between two speeds of the grid.
		last = spends.indexOf(Math.min(...spends));
		lo = polish(spend, speeds[last], step, speeds[0], topKms);
		if (spend(lo) > limit) return null;
	}
	const hi = speeds[Math.min(last + 1, CRUISE_GRID)];
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
		} else if (!best || plan.cruiseKms > best.cruiseKms) best = plan;
	}
	if (!best) return refusal;
	const slowness = (jd: number) => {
		const plan = planAt(jd);
		return typeof plan === 'string' ? Infinity : -plan.cruiseKms;
	};
	const jd = polish(slowness, best.departJd, step, fromJd, fromJd + periodDays);
	const polished = jd === best.departJd ? best : planAt(jd);
	return typeof polished === 'string' ? best : polished;
}

/**
 * The coast between two systems for a craft with a Δv budget or a launch curve.
 *
 * The craft leaves at the highest cruise speed its Δv allows, after it keeps
 * back what the arrival needs. The ascent is not spent from the budget. It
 * belongs to whatever launched the craft. A launcher has no Δv after the
 * launch, so it can only fly by. The time spent in the two wells is left out of
 * the crossing.
 *
 * A refusal when the craft cannot escape or cannot stop. Null when the two
 * stars are in one place.
 */
export function buildInterstellarCruiseRoute(
	origin: SystemEnd,
	target: SystemEnd,
	departJd: number,
	drive: Exclude<InterstellarDrive, { kind: 'torch' }>,
	options: InterstellarCruiseOptions = {}
): Route | InterstellarRefusal | null {
	const { departureMode = 'surface', arrivalMode = 'capture', aero = 'none' } = options;
	const distanceKm = starDistanceKm(origin, target);
	if (!(distanceKm > 0)) return null;
	const toward = scale(sub(target.starKm, origin.starKm), 1 / distanceKm);
	const stops = arrivalMode !== 'flyby';
	const site = surfaceSite(origin.body, options.departureSiteLatDeg, null);

	const leave = (state: StateVector | null, cruiseKms: number): Leaving => {
		if (origin.atStar) {
			const injectionKms = starPassKms(origin.starMu ?? 0, cruiseKms);
			return { vInfKms: cruiseKms, cost: { ascentKms: 0, injectionKms, turnKms: 0, turnDeg: 0 } };
		}
		const vInfKms = throughWells(
			origin,
			state ? departureExcessKms(state, toward, cruiseKms) : cruiseKms
		);
		const cost = departureCost(origin.body, vInfKms, departureMode, options.departureOrbit, site);
		return { vInfKms, cost };
	};
	const arrive = (cruiseKms: number) => coastArrival(target, cruiseKms, arrivalMode, options);

	// A launcher is held to its excess speed, a craft with a budget to its Δv.
	const launched = drive.kind === 'launch';
	const limit =
		(launched ? Math.sqrt(Math.max(0, drive.c3Km2S2)) : drive.dvKms) * (1 - LIMIT_MARGIN);
	const leaveSpend = ({ vInfKms, cost }: Leaving) => (launched ? vInfKms : cost.injectionKms);

	const planAt = (jd: number): CoastPlan | InterstellarRefusal => {
		const state = orbitStateAt(origin, jd);
		const scaleKms = limit + (state ? norm(state.v) : 0);
		const leaveOnly = (kms: number) => leaveSpend(leave(state, kms));
		const spend = (kms: number) => leaveOnly(kms) + (launched ? 0 : arrive(kms).spendKms);
		const cruiseKms = launched && stops ? null : fastestWithin(spend, limit, scaleKms);
		if (cruiseKms === null) {
			return fastestWithin(leaveOnly, limit, scaleKms) === null ? 'cannot-escape' : 'cannot-stop';
		}
		return {
			departJd: jd,
			cruiseKms,
			leaving: leave(state, cruiseKms),
			arrival: arrive(cruiseKms)
		};
	};

	const periodDays = 360 / meanMotionOf(origin);
	const plan =
		options.launchWindow && Number.isFinite(periodDays)
			? bestDate(planAt, departJd, periodDays)
			: planAt(departJd);
	if (typeof plan === 'string') return plan;

	const { leaving, arrival } = plan;
	const dep = leaving.cost;
	// A rocket gains c times a rapidity for its Δv, so the classical speed of the
	// plan is that figure. Read as one, a coast stays below c at any budget. At
	// tens of km/s the two speeds differ by a rounding error.
	const rapidity = plan.cruiseKms / C_KMS;
	const cruiseKms = C_KMS * Math.tanh(rapidity);
	const gamma = Math.cosh(rapidity);
	const tofDays = distanceKm / cruiseKms / SEC_PER_DAY;

	const legs: RouteLeg[] = [];
	if (dep.ascentKms > 0) legs.push({ kind: 'ascent', dvKms: dep.ascentKms, days: 0 });
	legs.push({ kind: 'injection', dvKms: dep.injectionKms, days: 0 });
	legs.push({ kind: 'cruise', dvKms: 0, days: tofDays, shipDays: tofDays / gamma });
	legs.push(...arrival.legs);

	return finishRoute(
		{
			departureId: origin.body.id,
			targetId: target.body.id,
			departJd: plan.departJd,
			arriveJd: plan.departJd + tofDays,
			tofDays,
			ascentKms: dep.ascentKms,
			c3Km2S2: characteristicEnergy(leaving.vInfKms),
			vInfDepKms: leaving.vInfKms,
			vInfArrKms: arrival.vInfKms,
			departureMode,
			arrivalMode,
			departureOrbit: options.departureOrbit,
			targetOrbit: options.targetOrbit,
			aero,
			entrySpeedKms: arrival.cost.entrySpeedKms,
			interstellar: { distanceKm, cruiseKms, gamma }
		},
		legs
	);
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
	/** Distance from the origin's star where the coast ends, km. */
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

/** Time from departure until the craft is `distanceKm` from the origin's star
 *  on a route between two systems, days, on the Earth's clock and on the
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
		const seconds = x / crossing.cruiseKms;
		return done(seconds, seconds / crossing.gamma);
	}

	const { accelKmS2, phi, burnKm, coastEndKm } = arc;
	const hold = C_KMS / accelKmS2;
	const speedKms = C_KMS * Math.tanh(phi);
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

/** How a crossing meets the matter at rest along it. */
export interface CrossingSweep {
	/** Distance from the origin's star where the craft first has its peak speed, km. */
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
		const peakExcess = lorentzExcess(crossing.cruiseKms);
		return { peakAtKm: 0, peakExcess, excessKm: peakExcess * crossing.distanceKm };
	}
	const peakExcess = 2 * Math.sinh(arc.phi / 2) ** 2;
	// Over a burn from rest the integral is (c²/a)(cosh φ − 1)²/2.
	const burnExcessKm = ((C_KMS * C_KMS) / arc.accelKmS2) * (peakExcess ** 2 / 2);
	return {
		peakAtKm: arc.burnKm,
		peakExcess,
		excessKm: arc.burns * burnExcessKm + peakExcess * (arc.coastEndKm - arc.burnKm)
	};
}

/** γ − 1 at `speedKms`, in a form that keeps its digits at low speed. */
function lorentzExcess(speedKms: number): number {
	const beta = speedKms / C_KMS;
	const root = Math.sqrt((1 - beta) * (1 + beta));
	return (beta * beta) / (root * (1 + root));
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
 * from `fromKm` to `toKm` from the origin's star. Null on any other route.
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
	if (!arc) return coast(Math.atanh(crossing.cruiseKms / C_KMS), hi - lo);

	const { accelKmS2, phi, burnKm, coastEndKm } = arc;
	// Each distance is from the end where the burn is at rest. The brake ends at the target's star.
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
