/**
 * The shape a route has in space, as opposed to what it costs.
 *
 * `Route` is a priced itinerary: legs, Δv, dates. None of that says where the
 * craft actually goes, and a trajectory drawn on the map has to. This module
 * rebuilds the geometry from the same inputs the route was priced from — the
 * builders are deterministic, so re-solving reproduces the very arc the ladder
 * is charging for, and nothing has to be carried across the worker boundary or
 * kept in step by hand.
 *
 * Everything here is in the transfer frame: km, ecliptic J2000, centred on
 * whatever the arc goes round. `centerId` names that body so the renderer can
 * hang the path off its live position rather than guessing at an origin.
 */

import type { TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { solveLambert } from './lambert';
import { parkingRadiusKm } from './maneuvers';
import { propagateState } from './propagate';
import type { Route, RouteOptions } from './route';
import { elementsToState } from './state';
import { relativeState, solveRadialArc } from './system-transfer';
import { add, cross, dot, norm, normalize, scale, sub, type Vec3 } from './vec3';

/**
 * A point on the trip worth marking. Burns and encounters, not every leg: an
 * ascent and the injection that follows it happen in the same place, and drawing
 * two markers on one pixel says less than drawing one.
 */
export type PathStopKind = 'departure' | 'assist' | 'arrival';

export interface PathStop {
	kind: PathStopKind;
	jd: number;
	/** Position in the transfer frame, km. */
	r: Vec3;
	/** The body the stop happens at. */
	bodyId: string;
	/** Δv spent here, km/s — the legs of the ladder that fall at this point. */
	dvKms: number;
}

/** How a stretch of the trip is flown. A cruise coasts; the other two are the
 *  halves of a drive held from one end to the other. */
export type PathArcKind = 'cruise' | 'boost' | 'brake';

export interface PathArc {
	kind: PathArcKind;
	/** Positions in the transfer frame, km, in flight order. */
	points: Vec3[];
	/**
	 * When each of `points` is passed, JD. Same length, and increasing.
	 *
	 * Carried rather than inferred from the index, because only a coasting arc is
	 * sampled evenly in time: a held drive is sampled evenly along its line, and a
	 * system transfer evenly in true anomaly. Anything asking *where the craft is
	 * now* has to read these rather than count samples.
	 */
	jds: number[];
	startJd: number;
	endJd: number;
}

export interface TrajectoryPath {
	/** The body every position here is measured from. */
	centerId: string;
	arcs: PathArc[];
	stops: PathStop[];
	/**
	 * Where the destination is at the moment the craft gets there.
	 *
	 * The whole reason an arc ends nowhere near where the destination is today:
	 * without this the path reads as missing.
	 */
	meeting: { bodyId: string; jd: number; r: Vec3 };
}

/** Somewhere on the drawn trajectory to look at, and how far back to look from. */
export interface PathViewpoint {
	/** Position in the transfer frame, km. */
	r: Vec3;
	/** A distance that frames what this point belongs to, km. */
	rangeKm: number;
}

/** How much of the arc's own length to stand back by. Enough that the leg reads
 *  as a curve rather than as the straight bit of it under the camera. */
const VIEW_RANGE_FRACTION = 0.6;
/** Nothing is framed closer than this, so a burn at one point still has a view. */
const MIN_VIEW_RANGE_KM = 1e4;

/**
 * Where to point the camera for the stretch of trip between `startJd` and
 * `endJd`.
 *
 * An instant (the two the same) lands on the stop or arc end it names; a stretch
 * lands in the middle of the arc that covers it, which is the one place the
 * whole of it is in view.
 *
 * Deliberately not "where the craft is at a given moment": the samples run even
 * in time on a coasting arc but even in true anomaly on a system transfer, and
 * the camera wants a place on the line rather than a claim about the craft.
 */
export function pathViewpoint(
	path: TrajectoryPath,
	startJd: number,
	endJd: number
): PathViewpoint | null {
	if (path.arcs.length === 0) return null;

	const chord = (arc: PathArc): number =>
		Math.max(MIN_VIEW_RANGE_KM, norm(sub(arc.points[arc.points.length - 1], arc.points[0])));

	// A stretch: the arc that runs alongside it, or failing an exact match the one
	// its middle falls inside.
	if (endJd > startJd) {
		const middle = (startJd + endJd) / 2;
		const arc =
			path.arcs.find((a) => a.startJd <= startJd + 1e-6 && a.endJd >= endJd - 1e-6) ??
			path.arcs.find((a) => a.startJd <= middle && a.endJd >= middle);
		if (!arc) return null;
		return {
			r: arc.points[Math.floor(arc.points.length / 2)],
			rangeKm: chord(arc) * VIEW_RANGE_FRACTION
		};
	}

	// An instant: a stop names one exactly, and every stop is an arc end.
	const stop = path.stops.find((s) => Math.abs(s.jd - startJd) < 1e-6);
	const nearest = path.arcs.reduce((best, arc) =>
		Math.abs(arc.startJd - startJd) < Math.abs(best.startJd - startJd) ? arc : best
	);
	const r =
		stop?.r ??
		(Math.abs(nearest.startJd - startJd) <= Math.abs(nearest.endJd - startJd)
			? nearest.points[0]
			: nearest.points[nearest.points.length - 1]);
	// Closer in than a whole leg: a burn happens at a place, and the arc either
	// side of it is what gives that place a shape.
	return { r, rangeKm: chord(nearest) * VIEW_RANGE_FRACTION * 0.25 };
}

export interface PathOptions extends RouteOptions {
	/** The body every position is measured from — the Sun for an ordinary
	 *  transfer, the primary for a trip inside one system. */
	centerId: string;
	/** Bodies a swing-by route passes. Only the one named by the route's flyby is
	 *  read; without it the second arc cannot be rebuilt. */
	vias?: readonly TravelBody[];
	/** Points per arc. The default draws a smooth ellipse at any zoom the map
	 *  reaches; a caller sampling for something other than a line may want fewer. */
	samples?: number;
}

const DEFAULT_SAMPLES = 180;

/** Δv of every leg of `kinds`, km/s. */
function dvOf(route: Route, kinds: readonly string[]): number {
	return route.legs.reduce((sum, leg) => (kinds.includes(leg.kind) ? sum + leg.dvKms : sum), 0);
}

/**
 * Sample the conic through `r`/`v` over `days`.
 *
 * The endpoints are placed exactly rather than propagated to: they are where
 * the bodies are, which is what the route was solved against, and a propagator
 * that drifts a few km over a year should not be what moves the marker off the
 * planet.
 */
function sampleConic(
	r: Vec3,
	v: Vec3,
	days: number,
	mu: number,
	samples: number,
	endpoint: Vec3
): Vec3[] | null {
	const points: Vec3[] = [r];
	const totalSec = days * SEC_PER_DAY;
	for (let i = 1; i < samples - 1; i++) {
		const point = propagateState(r, v, (totalSec * i) / (samples - 1), mu);
		// A propagation that will not settle mid-arc leaves a gap no line can be
		// drawn across honestly, so the whole arc goes rather than part of it.
		if (!point) return null;
		points.push(point);
	}
	points.push(endpoint);
	return points;
}

/** `count` dates spread evenly over `days` from `startJd`. */
function evenJds(startJd: number, days: number, count: number): number[] {
	const jds: number[] = [];
	for (let i = 0; i < count; i++) jds.push(startJd + (days * i) / (count - 1));
	return jds;
}

/** The Lambert arc between two bodies, sampled. */
function lambertArc(
	from: { r: Vec3; v: Vec3 },
	to: { r: Vec3 },
	startJd: number,
	days: number,
	mu: number,
	retrograde: boolean,
	samples: number
): PathArc | null {
	const arc = solveLambert(from.r, to.r, days * SEC_PER_DAY, mu, retrograde);
	if (!arc) return null;
	const points = sampleConic(from.r, arc.v1, days, mu, samples, to.r);
	if (!points) return null;
	// `sampleConic` propagates in equal time steps, so the dates are even too.
	return {
		kind: 'cruise',
		points,
		jds: evenJds(startJd, days, points.length),
		startJd,
		endJd: startJd + days
	};
}

/**
 * Rebuild the geometry of `route`.
 *
 * Returns null when the arc cannot be reproduced — a swing-by whose via body
 * was not supplied, or a solve that no longer converges. Drawing nothing is the
 * honest answer there; a straight line between the ends would not be the route.
 */
export function buildTrajectoryPath(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions
): TrajectoryPath | null {
	const {
		centerId,
		centralMu = GM_SUN_KM3_S2,
		retrograde = false,
		systemPrimary,
		vias = [],
		samples = DEFAULT_SAMPLES
	} = options;

	if (systemPrimary) {
		return systemPath(departure, target, route, centerId, systemPrimary, samples);
	}
	if (route.constantThrust != null) {
		return heldDrivePath(departure, target, route, centerId, centralMu, samples);
	}

	const from = elementsToState(departure.elements, route.departJd, centralMu);
	const to = elementsToState(target.elements, route.arriveJd, centralMu);
	if (!from || !to) return null;

	const departureStop: PathStop = {
		kind: 'departure',
		jd: route.departJd,
		r: from.r,
		bodyId: departure.id,
		dvKms: dvOf(route, ['ascent', 'injection'])
	};
	const arrivalStop: PathStop = {
		kind: 'arrival',
		jd: route.arriveJd,
		r: to.r,
		bodyId: target.id,
		dvKms: dvOf(route, ['capture', 'descent'])
	};
	const meeting = { bodyId: target.id, jd: route.arriveJd, r: to.r };

	const flyby = route.flybys?.[0];
	if (flyby) {
		const via = vias.find((body) => body.id === flyby.bodyId);
		if (!via) return null;
		const mid = elementsToState(via.elements, flyby.jd, centralMu);
		if (!mid) return null;

		const tof1 = flyby.jd - route.departJd;
		const tof2 = route.arriveJd - flyby.jd;
		const first = lambertArc(from, mid, route.departJd, tof1, centralMu, retrograde, samples);
		const second = lambertArc(mid, to, flyby.jd, tof2, centralMu, retrograde, samples);
		if (!first || !second) return null;

		return {
			centerId,
			arcs: [first, second],
			stops: [
				departureStop,
				{
					kind: 'assist',
					jd: flyby.jd,
					r: mid.r,
					bodyId: via.id,
					dvKms: flyby.dvKms
				},
				arrivalStop
			],
			meeting
		};
	}

	const arc = lambertArc(from, to, route.departJd, route.tofDays, centralMu, retrograde, samples);
	if (!arc) return null;
	return { centerId, arcs: [arc], stops: [departureStop, arrivalStop], meeting };
}

/**
 * A drive held all the way: a straight line in the frame it is flown in.
 *
 * The route was solved on exactly that assumption — the crossing is timed from
 * the distance to where the destination will be — so the flip falls at the
 * halfway point of the line rather than of the clock.
 */
function heldDrivePath(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	centerId: string,
	centralMu: number,
	samples: number
): TrajectoryPath | null {
	const from = elementsToState(departure.elements, route.departJd, centralMu);
	const to = elementsToState(target.elements, route.arriveJd, centralMu);
	if (!from || !to) return null;
	return straightCrossing(from.r, to.r, route, centerId, departure.id, target.id, samples);
}

/** The two halves of a held drive between two fixed points. */
function straightCrossing(
	start: Vec3,
	end: Vec3,
	route: Route,
	centerId: string,
	departureId: string,
	targetId: string,
	samples: number
): TrajectoryPath | null {
	const span = sub(end, start);
	if (!(norm(span) > 0)) return null;

	// Nothing to slow down for at a flyby, so the drive never flips and the
	// crossing is one arc.
	const flips = route.legs.some((leg) => leg.kind === 'brake');
	const midJd = route.departJd + route.tofDays / 2;
	const half = Math.max(2, Math.round(samples / 2));

	/**
	 * A stretch of the line, sampled evenly along it.
	 *
	 * Evenly along it is *not* evenly in time: a drive covers ground as ½at², so
	 * the craft crawls at the start of a burn and is fastest at the end of one.
	 * `timeFraction` turns a sample's place on the line into the fraction of the
	 * stretch's time it is reached at, which is what the dates are built from.
	 */
	const line = (
		fromT: number,
		toT: number,
		count: number,
		fromJd: number,
		toJd: number,
		timeFraction: (along: number) => number
	): { points: Vec3[]; jds: number[] } => {
		const points: Vec3[] = [];
		const jds: number[] = [];
		for (let i = 0; i < count; i++) {
			const along = i / (count - 1);
			points.push(add(start, scale(span, fromT + (toT - fromT) * along)));
			jds.push(fromJd + (toJd - fromJd) * timeFraction(along));
		}
		return { points, jds };
	};

	// Accelerating from rest, distance goes as the square of the time — so the
	// time is the square root of the distance. Braking is the same run backwards.
	const accelerating = (along: number) => Math.sqrt(along);
	const braking = (along: number) => 1 - Math.sqrt(Math.max(0, 1 - along));

	const arcs: PathArc[] = flips
		? [
				{
					kind: 'boost',
					...line(0, 0.5, half, route.departJd, midJd, accelerating),
					startJd: route.departJd,
					endJd: midJd
				},
				{
					kind: 'brake',
					...line(0.5, 1, half, midJd, route.arriveJd, braking),
					startJd: midJd,
					endJd: route.arriveJd
				}
			]
		: [
				{
					kind: 'boost',
					...line(0, 1, samples, route.departJd, route.arriveJd, accelerating),
					startJd: route.departJd,
					endJd: route.arriveJd
				}
			];

	return {
		centerId,
		arcs,
		stops: [
			{
				kind: 'departure',
				jd: route.departJd,
				r: start,
				bodyId: departureId,
				dvKms: dvOf(route, ['ascent', 'injection'])
			},
			{
				kind: 'arrival',
				jd: route.arriveJd,
				r: end,
				bodyId: targetId,
				dvKms: dvOf(route, ['capture', 'descent'])
			}
		],
		meeting: { bodyId: targetId, jd: route.arriveJd, r: end }
	};
}

/**
 * A trip between a body and one of its own satellites.
 *
 * The pricing model fixes the arc's energy and its two radii but not its plane —
 * it never needed one. Drawing does, and the satellite's own plane is the one a
 * real mission flies: the arc leaves a parking orbit at periapsis and climbs to
 * meet the satellite where it is, so the sweep is periapsis to the satellite's
 * true anomaly and the plane is the one it is met in.
 */
function systemPath(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	centerId: string,
	systemPrimary: 'departure' | 'target',
	samples: number
): TrajectoryPath | null {
	const outbound = systemPrimary === 'departure';
	const primary = outbound ? departure : target;
	const satellite = outbound ? target : departure;
	// The satellite's distance is read at the end of the trip it is at, matching
	// how the route was priced.
	const meetJd = outbound ? route.arriveJd : route.departJd;
	const state = relativeState(satellite, primary, meetJd);
	if (!state) return null;

	const rFar = norm(state.r);
	const rNear = parkingRadiusKm(primary);
	if (!(rFar > 0) || !(rNear > 0)) return null;

	const meeting = {
		bodyId: target.id,
		jd: route.arriveJd,
		r: outbound ? state.r : ([0, 0, 0] as Vec3)
	};
	const departureStop: PathStop = {
		kind: 'departure',
		jd: route.departJd,
		r: outbound ? scale(normalize(state.r), rNear) : state.r,
		bodyId: departure.id,
		dvKms: dvOf(route, ['ascent', 'injection'])
	};
	const arrivalStop: PathStop = {
		kind: 'arrival',
		jd: route.arriveJd,
		r: outbound ? state.r : scale(normalize(state.r), rNear),
		bodyId: target.id,
		dvKms: dvOf(route, ['capture', 'descent'])
	};

	if (route.constantThrust != null) {
		// A held drive ignores the transfer ellipse entirely: it crosses in a
		// straight line between the primary's parking orbit and the satellite.
		const parking = scale(normalize(state.r), rNear);
		return straightCrossing(
			outbound ? parking : state.r,
			outbound ? state.r : parking,
			route,
			centerId,
			departure.id,
			target.id,
			samples
		);
	}

	const arc = solveRadialArc(primary.mu, rNear, rFar, route.tofDays);
	if (!arc) return null;

	const a = 1 / arc.inverseAKm;
	const e = 1 - rNear * arc.inverseAKm;
	const p = a * (1 - e * e);
	if (!isFinite(p) || !(p > 0)) return null;

	// True anomaly where the arc meets the satellite, from the conic equation.
	const cosNu = (p / rFar - 1) / (e || 1e-12);
	const nuFar = Math.acos(Math.max(-1, Math.min(1, cosNu)));
	if (!isFinite(nuFar)) return null;

	// The plane is the satellite's, and periapsis sits `nuFar` behind it along
	// the direction the satellite is travelling.
	const normal = normalize(cross(state.r, state.v));
	if (!(norm(normal) > 0)) return null;
	const far = normalize(state.r);
	// Rotate `far` back by nuFar about the normal (Rodrigues, on unit vectors).
	const cosBack = Math.cos(-nuFar);
	const sinBack = Math.sin(-nuFar);
	const periapsis = normalize(
		add(
			add(scale(far, cosBack), scale(cross(normal, far), sinBack)),
			scale(normal, dot(normal, far) * (1 - cosBack))
		)
	);
	const inPlane = normalize(cross(normal, periapsis));

	const points: Vec3[] = [];
	// Time from periapsis to each sample, so the dates can be recovered from an
	// arc that is sampled evenly in angle rather than evenly in time. Kepler's
	// equation, in whatever unit the ratio below cancels out.
	const sincePeriapsis: number[] = [];
	for (let i = 0; i < samples; i++) {
		const nu = (nuFar * i) / (samples - 1);
		const radius = p / (1 + e * Math.cos(nu));
		if (!isFinite(radius) || radius <= 0) return null;
		points.push(scale(add(scale(periapsis, Math.cos(nu)), scale(inPlane, Math.sin(nu))), radius));
		const anomaly =
			2 * Math.atan2(Math.sqrt(1 - e) * Math.sin(nu / 2), Math.sqrt(1 + e) * Math.cos(nu / 2));
		sincePeriapsis.push(anomaly - e * Math.sin(anomaly));
	}

	// Scaled to the flight time the arc was solved for rather than to a period
	// derived here, so the ends land exactly on the two dates the route names.
	const sweep = sincePeriapsis[samples - 1];
	const elapsed = sincePeriapsis.map((mean) =>
		sweep > 0 && isFinite(sweep) ? (route.tofDays * mean) / sweep : 0
	);
	const jds = outbound
		? elapsed.map((days) => route.departJd + days)
		: // Read the same arc backwards on the way home: the far end is left first.
			elapsed.map((days) => route.arriveJd - days).reverse();
	if (!outbound) points.reverse();

	return {
		centerId,
		arcs: [{ kind: 'cruise', points, jds, startJd: route.departJd, endJd: route.arriveJd }],
		stops: [departureStop, arrivalStop],
		meeting
	};
}
