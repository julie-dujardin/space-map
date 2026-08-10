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

import { AU_KM } from '$lib/math/units';
import { sphereOfInfluenceKm, type TravelBody } from './body';
import { GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { sampleHeldDrive, type HeldDriveSample } from './held-drive';
import { solveLambert } from './lambert';
import { rebuildSpiral } from './low-thrust';
import { endArrivalOrbit, endDepartureOrbit, parkingRadiusKm, type EndOrbit } from './maneuvers';
import { propagateState } from './propagate';
import { routeDurationDays, type Route, type RouteOptions } from './route';
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

/**
 * How a stretch of the trip is flown.
 *
 * A cruise coasts, the next two are the halves of a drive held from one end to
 * the other, and the last three are what a drive too weak to burn does: the
 * crossing, and the months of revolutions round a body at each end of it. Those
 * two are drawn as the body's own path, because at the scale a transfer is drawn
 * at, that is exactly where the craft is — the spiral itself is thousands of
 * loops inside a dot.
 */
export type PathArcKind = 'cruise' | 'boost' | 'brake' | 'spiral' | 'spiral-out' | 'spiral-in';

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

/**
 * An end of a trip, drawn round the body it happens at: the orbit the craft is
 * in there, and the passage between that orbit and the crossing.
 *
 * Only the ends that are an orbit: a launch from the ground and a landing on it
 * are not, and neither is a flyby. It sits where the body will be on the date
 * that end of the trip happens, like everything else here — the same place the
 * arc meets it.
 */
export interface EndOrbitPath {
	at: 'departure' | 'arrival';
	bodyId: string;
	/** The closed orbit, in the transfer frame, km. */
	points: Vec3[];
	/**
	 * The escape or capture between the sphere of influence and the orbit's
	 * periapsis, in flight order and the same frame, carrying on from the last
	 * sample of the crossing left outside. It shares periapsis with the orbit, so
	 * the two meet along one tangent.
	 *
	 * Empty at an end whose model has no passage to draw: a drive held all the way
	 * and a spiral arrive under thrust rather than on a conic, and a transfer
	 * inside one system leaves the primary's parking orbit without ever escaping.
	 */
	approach: Vec3[];
	/**
	 * The stretch of the crossing this passage replaces, as a half-open range of
	 * sample indices into the arc that meets this body. Whoever draws the
	 * crossing draws only `[trimFrom, trimTo)` and lets `approach` finish it —
	 * left whole, the arc would run to the body's centre and cut through the
	 * orbit round it. The full range where there is nothing to replace.
	 */
	trimFrom: number;
	trimTo: number;
	/** The body's centre in the same frame, km — what both go round. */
	center: Vec3;
	/**
	 * The date the craft is at this end's periapsis, which is the date `center`
	 * places the body at. At a departure this is the injection burn, so it is the
	 * route's own date; at an arrival it is solved — the crossing was priced to
	 * the body's centre, a place the craft never goes, and the real periapsis
	 * comes hours earlier, with the body a sphere-of-influence's width away from
	 * where the pricing left it.
	 */
	periJd: number;
	/** The orbit's widest radius, km. What says whether it is worth drawing at
	 *  all: at system scale a parking orbit is well inside the dot the planet is
	 *  drawn as. */
	radiusKm: number;
}

export interface TrajectoryPath {
	/** The body every position here is measured from. */
	centerId: string;
	arcs: PathArc[];
	stops: PathStop[];
	/** The orbits at either end, where those ends are orbits. */
	endOrbits: EndOrbitPath[];
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
	// its middle falls inside. The two spiral ends are skipped — they are a body's
	// own path, so framing the swath of orbit they cover would point the camera
	// anywhere but at the body the craft is going round.
	if (endJd > startJd) {
		const middle = (startJd + endJd) / 2;
		const crossings = path.arcs.filter((a) => a.kind !== 'spiral-out' && a.kind !== 'spiral-in');
		const arc =
			crossings.find((a) => a.startJd <= startJd + 1e-6 && a.endJd >= endJd - 1e-6) ??
			crossings.find((a) => a.startJd <= middle && a.endJd >= middle);
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

/** A trajectory before the orbits at its ends are hung off it — what each of the
 *  builders below answers with. */
type PathGeometry = Omit<TrajectoryPath, 'endOrbits'>;

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
	const path = buildCrossing(departure, target, route, options);
	if (!path) return null;
	const endOrbits = endOrbitPaths(departure, target, route, options, path);
	// An arrival passage re-dates the encounter and the meeting follows it —
	// left behind, it would mark a spot the body has already left and the ring
	// would circle nothing. The stops stay priced: they are where the arcs end,
	// which is where the scrubbed craft ends up.
	const arrival = endOrbits.find((end) => end.at === 'arrival' && end.approach.length > 0);
	if (!arrival) return { ...path, endOrbits };
	return {
		...path,
		meeting: { ...path.meeting, jd: arrival.periJd, r: arrival.center },
		endOrbits
	};
}

function buildCrossing(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions
): PathGeometry | null {
	const {
		centerId,
		centralMu = GM_SUN_KM3_S2,
		retrograde = false,
		systemPrimary,
		vias = [],
		samples = DEFAULT_SAMPLES
	} = options;

	if (route.lowThrust) {
		// A spiral inside one system is thousands of revolutions deep, which is a
		// shape rather than a line: there is nothing to draw between the two ends
		// that would not be a lie about how many times round it went.
		if (systemPrimary) return null;
		return spiralPath(departure, target, route, centerId, centralMu);
	}
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

/** Points round an end orbit. Enough that the ring is a curve at the zoom it
 *  starts being drawn at, which is a body filling a good part of the screen. */
const RING_SAMPLES = 96;
/** Points along a passage. Spread evenly in true anomaly, so they crowd where
 *  the path is bending and thin out where it is already its own asymptote. */
const PASSAGE_SAMPLES = 160;
/** How far out a passage is drawn when the sphere of influence cannot be worked
 *  out, and the most it is ever drawn to. Earth's own sphere is 140 parking
 *  radii, so this only ever catches the bodies whose orbit is not known. */
const PASSAGE_MAX_RADII = 200;

/**
 * The orbits at the ends of a trip, and the passages that join them to the
 * crossing.
 *
 * Both sit where the body is on the date the craft is at that end's periapsis:
 * at a departure the parking orbit the injection burn is made from and the
 * escape it leaves on, at an arrival the approach and the orbit the insertion
 * leaves the craft in. A departure's date is the route's own; an arrival's is
 * solved by the passage, which knows where the crossing really left off.
 *
 * Patched conics, drawn the way they are flown. The two radii and the excess
 * speed are what the pricing fixed; the plane is free, and is taken as near the
 * plane of the arc as an asymptote allows, so the passage reads as that line
 * continuing rather than as a hoop stood on edge. Where there is a passage it
 * also fixes the orbit's low point — the insertion burn is made there, so the
 * two meet along the same tangent and the trip turns into its orbit rather than
 * arriving beside one.
 */
function endOrbitPaths(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions,
	path: PathGeometry
): EndOrbitPath[] {
	const centers = endCenters(departure, target, route, options);
	const first = path.arcs[0];
	const last = path.arcs[path.arcs.length - 1];
	if (!centers || !first || !last) return [];

	const { centralMu = GM_SUN_KM3_S2, systemPrimary } = options;
	// What each end body goes round, which is what its sphere of influence is
	// measured against: the primary itself inside one system, the Sun elsewhere.
	const primaryMu = systemPrimary
		? (systemPrimary === 'departure' ? departure : target).mu
		: centralMu;
	const approaches = endApproaches(departure, target, route, options);

	const orbits: EndOrbitPath[] = [];
	const from = endDepartureOrbit(departure, route.departureMode, route.departureOrbit);
	if (from) {
		orbits.push(
			endOrbitPath({
				at: 'departure',
				body: departure,
				center: centers.from,
				orbit: from,
				arc: first,
				periJd: route.departJd,
				approach: approaches.from,
				primaryMu
			})
		);
	}
	const to = endArrivalOrbit(target, route.arrivalMode, route.targetOrbit);
	if (to) {
		orbits.push(
			endOrbitPath({
				at: 'arrival',
				body: target,
				center: centers.to,
				orbit: to,
				arc: last,
				periJd: route.arriveJd,
				approach: approaches.to,
				primaryMu
			})
		);
	}
	return orbits;
}

/**
 * How the craft meets each end body, re-solved rather than carried, like the
 * arcs themselves.
 *
 * The body comes as a function of time rather than a frozen state because the
 * passage needs it as one twice over: {@link soiCrossingJd} chases it to find
 * where the crossing really enters its sphere of influence, and
 * {@link hyperbolicPassage} carries its true displacement so the drawn line is
 * the patched-conic worldline, not a straight-line stand-in for it.
 *
 * Absent at an end with no hyperbolic passage to draw, which is more ends than
 * it sounds: a drive held all the way and a spiral both arrive under thrust
 * rather than on a conic, and inside one system the craft never escapes the
 * primary at all — the transfer ellipse leaves its parking orbit at periapsis,
 * so the ring is already tangent to the arc with nothing in between.
 */
interface EndApproach {
	/** Excess velocity, km/s: the craft's own less the body's. */
	vInf: Vec3;
	/** The body's position at `jd` in the transfer frame, km. */
	bodyAt: (jd: number) => Vec3 | null;
	/** The craft's state on the crossing conic at this end's priced date — what
	 *  the sphere-of-influence crossing is solved against. */
	craft: { r: Vec3; v: Vec3; jd: number };
	/** The μ the crossing conic is flown under. */
	crossingMu: number;
}

function endApproaches(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions
): { from?: EndApproach; to?: EndApproach } {
	const { centralMu = GM_SUN_KM3_S2, retrograde = false, systemPrimary, vias = [] } = options;
	if (route.lowThrust || route.constantThrust != null) return {};

	if (systemPrimary) {
		// Only the way out. Coming home, the model prices the departure off the
		// excess speed the *outward* leg has at the satellite, which is not the
		// velocity the drawn arc leaves with — and drawing one shape while pricing
		// another is the one thing this module refuses to do.
		if (systemPrimary !== 'departure') return {};
		const state = relativeState(target, departure, route.arriveJd);
		if (!state) return {};
		const arc = solveRadialArc(
			departure.mu,
			parkingRadiusKm(departure),
			norm(state.r),
			route.tofDays
		);
		const normal = cross(state.r, state.v);
		if (!arc || !(norm(normal) > 0)) return {};
		// The arc's own velocity where it meets the satellite, put back together
		// from the two components it was solved in: climbing, and going round.
		const outward = normalize(state.r);
		const along = normalize(cross(normal, outward));
		const vArc = add(scale(outward, arc.vFarRadialKms), scale(along, arc.vFarTangentialKms));
		return {
			to: {
				vInf: sub(vArc, state.v),
				bodyAt: (jd) => relativeState(target, departure, jd)?.r ?? null,
				craft: { r: state.r, v: vArc, jd: route.arriveJd },
				crossingMu: departure.mu
			}
		};
	}

	const from = elementsToState(departure.elements, route.departJd, centralMu);
	const to = elementsToState(target.elements, route.arriveJd, centralMu);
	if (!from || !to) return {};
	const departureAt = (jd: number) => elementsToState(departure.elements, jd, centralMu)?.r ?? null;
	const targetAt = (jd: number) => elementsToState(target.elements, jd, centralMu)?.r ?? null;

	const flyby = route.flybys?.[0];
	if (flyby) {
		const via = vias.find((body) => body.id === flyby.bodyId);
		const mid = via ? elementsToState(via.elements, flyby.jd, centralMu) : null;
		if (!mid) return {};
		const out = solveLambert(
			from.r,
			mid.r,
			(flyby.jd - route.departJd) * SEC_PER_DAY,
			centralMu,
			retrograde
		);
		const back = solveLambert(
			mid.r,
			to.r,
			(route.arriveJd - flyby.jd) * SEC_PER_DAY,
			centralMu,
			retrograde
		);
		if (!out || !back) return {};
		return {
			from: {
				vInf: sub(out.v1, from.v),
				bodyAt: departureAt,
				craft: { r: from.r, v: out.v1, jd: route.departJd },
				crossingMu: centralMu
			},
			to: {
				vInf: sub(back.v2, to.v),
				bodyAt: targetAt,
				craft: { r: to.r, v: back.v2, jd: route.arriveJd },
				crossingMu: centralMu
			}
		};
	}

	const arc = solveLambert(from.r, to.r, route.tofDays * SEC_PER_DAY, centralMu, retrograde);
	if (!arc) return {};
	return {
		from: {
			vInf: sub(arc.v1, from.v),
			bodyAt: departureAt,
			craft: { r: from.r, v: arc.v1, jd: route.departJd },
			crossingMu: centralMu
		},
		to: {
			vInf: sub(arc.v2, to.v),
			bodyAt: targetAt,
			craft: { r: to.r, v: arc.v2, jd: route.arriveJd },
			crossingMu: centralMu
		}
	};
}

/** Where each end's body is, in the transfer frame, on the date the trip is
 *  there. Null when either cannot be placed, which is when nothing is drawn. */
function endCenters(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions
): { from: Vec3; to: Vec3 } | null {
	const { centralMu = GM_SUN_KM3_S2, systemPrimary } = options;
	// Inside one system the primary *is* the frame, so it sits at the origin and
	// only the satellite has to be placed.
	if (systemPrimary) {
		const outbound = systemPrimary === 'departure';
		const primary = outbound ? departure : target;
		const satellite = outbound ? target : departure;
		const state = relativeState(satellite, primary, outbound ? route.arriveJd : route.departJd);
		if (!state) return null;
		const center: Vec3 = [0, 0, 0];
		return outbound ? { from: center, to: state.r } : { from: state.r, to: center };
	}
	const from = elementsToState(departure.elements, route.departJd, centralMu);
	const to = elementsToState(target.elements, route.arriveJd, centralMu);
	if (!from || !to) return null;
	return { from: from.r, to: to.r };
}

/**
 * One end of a trip: the orbit, and the passage down to it where there is one.
 *
 * The plane and the direction of travel come from the two samples of the
 * crossing nearest this body, in flight order. Without an approach that is all
 * there is to go on, and the orbit's low point is put on the side the craft
 * comes from.
 *
 * `arc` is the stretch of crossing that meets this body, and `periJd` the
 * route's date for this end — the passage may re-date its low point from there,
 * and the crossing's own last step is cut against whichever date stands.
 */
function endOrbitPath(end: {
	at: 'departure' | 'arrival';
	body: TravelBody;
	center: Vec3;
	orbit: EndOrbit;
	arc: PathArc;
	periJd: number;
	approach?: EndApproach;
	primaryMu: number;
}): EndOrbitPath {
	const { at, body, center, orbit, arc, periJd, approach, primaryMu } = end;
	const outward = at === 'departure';
	const count = arc.points.length;
	// The two samples this end meets the body at, in flight order.
	const a = outward ? arc.points[0] : arc.points[count - 2];
	const b = outward ? arc.points[1] : arc.points[count - 1];
	// The ecliptic's own normal for an arc with no plane to read — two samples on
	// top of each other, or a radial arc seen exactly edge on.
	const crossed = cross(a, b);
	const arcNormal = norm(crossed) > 0 ? normalize(crossed) : ([0, 0, 1] as Vec3);

	const passage = approach
		? hyperbolicPassage({
				body,
				approach,
				rPeriKm: orbit.rPeriKm,
				arcNormal,
				at,
				primaryMu,
				center,
				arc,
				endJd: periJd
			})
		: null;
	const normal = passage?.normal ?? arcNormal;
	const periapsis = passage?.periapsis ?? approachSide(arcNormal, a, b);
	// A passage re-dates its end, and the ring goes round the body where the
	// body then is; without one the priced date stands.
	const ringCenter = passage?.center ?? center;

	return {
		at,
		bodyId: body.id,
		points: closedOrbit(ringCenter, orbit, normal, periapsis),
		approach: passage ? passage.points.map((point) => add(ringCenter, point)) : [],
		trimFrom: passage && outward ? passage.cut : 0,
		trimTo: passage && !outward ? passage.cut + 1 : count,
		center: ringCenter,
		periJd: passage?.periJd ?? periJd,
		radiusKm: orbit.rApoKm
	};
}

/** Index of the last date at or before `jd`, or -1 when there is none. */
function lastBefore(jds: readonly number[], jd: number): number {
	let index = -1;
	for (let i = 0; i < jds.length; i++) if (jds[i] <= jd) index = i;
	return index;
}

/** Index of the first date at or after `jd`, or -1 when there is none. */
function firstAfter(jds: readonly number[], jd: number): number {
	for (let i = 0; i < jds.length; i++) if (jds[i] >= jd) return i;
	return -1;
}

/** Which way the craft came from, in the plane, for an end with no passage to
 *  take a low point from. */
function approachSide(normal: Vec3, a: Vec3, b: Vec3): Vec3 {
	const back = scale(sub(b, a), -1);
	const along = sub(back, scale(normal, dot(normal, back)));
	return norm(along) > 0 ? normalize(along) : perpendicularTo(normal);
}

/** A bound orbit as a closed ring about `center`, low point along `periapsis`. */
function closedOrbit(center: Vec3, orbit: EndOrbit, normal: Vec3, periapsis: Vec3): Vec3[] {
	const inPlane = normalize(cross(normal, periapsis));
	const semiMajor = (orbit.rPeriKm + orbit.rApoKm) / 2;
	const e = (orbit.rApoKm - orbit.rPeriKm) / (orbit.rApoKm + orbit.rPeriKm);
	const p = semiMajor * (1 - e * e);

	const points: Vec3[] = [];
	for (let i = 0; i <= RING_SAMPLES; i++) {
		const nu = (Math.PI * 2 * i) / RING_SAMPLES;
		const radius = p / (1 + e * Math.cos(nu));
		const direction = add(scale(periapsis, Math.cos(nu)), scale(inPlane, Math.sin(nu)));
		points.push(add(center, scale(direction, radius)));
	}
	return points;
}

/**
 * The escape or capture an end of a trip is flown on, in flight order: from the
 * crossing down to periapsis, or from periapsis back out to it.
 *
 * The conic is all derived — eccentricity from the excess speed and the periapsis
 * the burn is made at, and the angle between periapsis and the asymptote from the
 * eccentricity. What is chosen rather than derived is the plane: every plane
 * holding the asymptote is a possible approach, and the one taken is the nearest
 * of them to the crossing's own.
 *
 * Its dates are its own rather than the route's. The route prices an arrival as
 * the crossing reaching the body's centre, a place the craft never goes: really
 * it leaves the crossing where that crosses the moving sphere of influence, and
 * is at periapsis a hyperbolic fall later — hours before the priced date, with
 * the body somewhere else by then. `periJd` and `center` answer with that
 * corrected meeting; a departure keeps its date, since its periapsis is the
 * injection burn the route priced.
 *
 * **The two frames are blended across it, and that is the point.** A hyperbola
 * about the body is only the trajectory to someone standing on the body; the
 * crossing outside is drawn about the Sun, and the two differ by the body's own
 * motion — 24 km/s at Mars against a 9 km/s arrival. Drawn one after the other
 * they read as the trip turning a corner in deep space. So every sample carries
 * the body's true displacement between it and periapsis, weighted from all of it
 * where the crossing hands over down to none of it at periapsis: out there the
 * drawn line is the patched-conic worldline itself; at periapsis it is the
 * hyperbola, tangent to the orbit it turns into, round a body the map holds
 * still. In between it trades one for the other, which no single frame could.
 *
 * The handover is put on a sample of the crossing rather than on a radius, and
 * whatever the conic misses by there is carried under the same weight, so the
 * two lines meet at a point they share exactly and part company gradually.
 *
 * Null where there is no passage to draw — a body with no μ to speak of, an
 * excess speed of zero, or a crossing too short to give one up.
 */
function hyperbolicPassage(end: {
	body: TravelBody;
	approach: EndApproach;
	rPeriKm: number;
	arcNormal: Vec3;
	at: 'departure' | 'arrival';
	primaryMu: number;
	center: Vec3;
	arc: PathArc;
	endJd: number;
}): {
	points: Vec3[];
	periapsis: Vec3;
	normal: Vec3;
	cut: number;
	center: Vec3;
	periJd: number;
} | null {
	const { body, approach, rPeriKm, arcNormal, at, primaryMu, arc, endJd } = end;
	const { vInf, bodyAt } = approach;
	const speed = norm(vInf);
	if (!(speed > 0) || !(body.mu > 0) || !(rPeriKm > 0)) return null;

	const outward = at === 'departure';
	const asymptote = normalize(vInf);
	const off = sub(arcNormal, scale(asymptote, dot(arcNormal, asymptote)));
	const normal = norm(off) > 0 ? normalize(off) : perpendicularTo(asymptote);

	const e = 1 + (rPeriKm * speed * speed) / body.mu;
	if (!(e > 1)) return null;
	const p = rPeriKm * (1 + e);
	// True anomaly of the asymptote: the craft leaves along it that far after
	// periapsis, and arrives along it the same angle before.
	const nuInf = Math.acos(-1 / e);
	const periapsis = outward
		? rotateAbout(asymptote, normal, -nuInf)
		: rotateAbout(scale(asymptote, -1), normal, nuInf);
	const inPlane = normalize(cross(normal, periapsis));

	const outer = passageRadiusKm(body, primaryMu, rPeriKm);
	const nuOuter = Math.acos(Math.max(-1, Math.min(1, (p / outer - 1) / e)));
	if (!(nuOuter > 0)) return null;

	// The fall between the sphere of influence and periapsis, and where the
	// crossing really crosses the sphere — chased against the moving body, with
	// the hyperbola's own clock as the stand-in when the chase fails.
	const meanMotion = Math.sqrt(body.mu / Math.abs(p / (1 - e * e)) ** 3);
	const fallDays = hyperbolicSeconds(e, nuOuter, meanMotion) / SEC_PER_DAY;
	const crossJd =
		soiCrossingJd(approach, outer, outward) ?? endJd + (outward ? fallDays : -fallDays);
	const periJd = outward ? endJd : crossJd + fallDays;
	const center = bodyAt(periJd);
	if (!center) return null;

	// Where the crossing gives way: its last sample still outside the sphere.
	// Anything closer in belongs to the body, not to whatever the crossing rounds.
	const cut = outward ? firstAfter(arc.jds, crossJd) : lastBefore(arc.jds, crossJd);
	// One sample either side at least, or there is no line left to draw.
	if (cut < 1 || cut > arc.points.length - 2) return null;

	// Sampled in time rather than in angle, and squared so the samples crowd at
	// periapsis where the line bends. Even steps in true anomaly would put a
	// million kilometres between the first two, out where the passage is really
	// parameterised by the body's motion rather than by its own.
	const joinDays = arc.jds[cut] - periJd;
	const sample = (days: number): Vec3 => {
		const nu = hyperbolicTrueAnomaly(e, days * SEC_PER_DAY * meanMotion);
		const radius = p / (1 + e * Math.cos(nu));
		const direction = add(scale(periapsis, Math.cos(nu)), scale(inPlane, Math.sin(nu)));
		return scale(direction, radius);
	};
	const carried = (days: number): Vec3 | null => {
		const moved = bodyAt(periJd + days);
		return moved ? sub(moved, center) : null;
	};
	const joinCarried = carried(joinDays);
	if (!joinCarried) return null;
	// What the conic misses the crossing by where the two meet, carried under the
	// same weight as the body's motion — so the join is exact and nothing of it
	// is left by the time the passage reaches its orbit.
	const miss = sub(sub(arc.points[cut], center), add(sample(joinDays), joinCarried));

	const points: Vec3[] = [];
	for (let i = 0; i < PASSAGE_SAMPLES; i++) {
		const along = i / (PASSAGE_SAMPLES - 1);
		const fraction = outward ? along : 1 - along;
		const days = joinDays * fraction * fraction;
		const point = sample(days);
		const moved = carried(days);
		if (!moved) return null;
		const weight = frameBlend((norm(point) - rPeriKm) / (outer - rPeriKm));
		points.push(add(point, scale(add(moved, miss), weight)));
	}
	return { points, periapsis, normal, cut, center, periJd };
}

/**
 * When the crossing crosses the body's sphere of influence, as a date.
 *
 * Solved against the moving body rather than read off the hyperbola's clock:
 * the two curves are `soiKm` apart somewhere the priced dates never name, since
 * the crossing was solved to the body's centre and the body does not wait
 * there. Walked out from that centre-meeting — the one date the two are
 * certainly inside the sphere — then bisected.
 *
 * Null when the walk never leaves the sphere, or either curve cannot be
 * evaluated; the caller falls back to the hyperbola's own clock.
 */
function soiCrossingJd(approach: EndApproach, soiKm: number, outward: boolean): number | null {
	const { vInf, bodyAt, craft, crossingMu } = approach;
	const speed = norm(vInf);
	if (!(speed > 0) || !(soiKm > 0)) return null;

	const separation = (jd: number): number | null => {
		const r = propagateState(craft.r, craft.v, (jd - craft.jd) * SEC_PER_DAY, crossingMu);
		const body = bodyAt(jd);
		return r && body ? norm(sub(r, body)) - soiKm : null;
	};

	const direction = outward ? 1 : -1;
	let step = soiKm / speed / SEC_PER_DAY / 2;
	let inside = craft.jd;
	let outside: number | null = null;
	for (let i = 0; i < 12 && outside === null; i++) {
		const jd = craft.jd + direction * step;
		const apart = separation(jd);
		if (apart === null) return null;
		if (apart >= 0) outside = jd;
		else inside = jd;
		step *= 2;
	}
	if (outside === null) return null;

	let edge = outside;
	for (let i = 0; i < 48; i++) {
		const mid = (inside + edge) / 2;
		const apart = separation(mid);
		if (apart === null) return null;
		if (apart >= 0) edge = mid;
		else inside = mid;
	}
	return (inside + edge) / 2;
}

/** How long after periapsis a hyperbola is at true anomaly `nu`, seconds, signed
 *  with `nu`. Kepler's equation for e > 1 — the passage has to carry dates to be
 *  blended against anything at all. */
function hyperbolicSeconds(e: number, nu: number, meanMotion: number): number {
	const tanHalf = Math.sqrt((e - 1) / (e + 1)) * Math.tan(nu / 2);
	const H = 2 * Math.atanh(Math.max(-1 + 1e-15, Math.min(1 - 1e-15, tanHalf)));
	return (e * Math.sinh(H) - H) / meanMotion;
}

/** The other way round: true anomaly at mean anomaly `m`, by Newton. */
function hyperbolicTrueAnomaly(e: number, m: number): number {
	let H = Math.asinh(m / e) || 0;
	for (let i = 0; i < 32; i++) {
		const f = e * Math.sinh(H) - H - m;
		const step = f / (e * Math.cosh(H) - 1);
		H -= step;
		if (Math.abs(step) < 1e-12) break;
	}
	return 2 * Math.atan(Math.sqrt((e + 1) / (e - 1)) * Math.tanh(H / 2));
}

/** How much of the other frame a point of the passage carries: none at
 *  periapsis, all of it where the crossing hands over. Flat at both ends, so the
 *  line meets the orbit and the crossing along a tangent rather than at an
 *  angle. */
function frameBlend(x: number): number {
	const t = Math.max(0, Math.min(1, x));
	return t * t * (3 - 2 * t);
}

/** How far out a passage is drawn: to the edge of the body's sphere of
 *  influence, which is where a patched conic stops meaning anything. */
function passageRadiusKm(body: TravelBody, primaryMu: number, rPeriKm: number): number {
	const soi = sphereOfInfluenceKm(body, primaryMu, Math.abs(body.elements.a) * AU_KM);
	const cap = rPeriKm * PASSAGE_MAX_RADII;
	return Number.isFinite(soi) && soi > rPeriKm ? Math.min(soi, cap) : cap;
}

/** Any unit vector at right angles to `n`. */
function perpendicularTo(n: Vec3): Vec3 {
	const axis: Vec3 = Math.abs(n[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0];
	return normalize(cross(n, axis));
}

/**
 * A drive held all the way, re-flown.
 *
 * The crossing is integrated under the primary's pull, so the only way to draw
 * the line it took is to fly it again. The route carries the one thing that
 * cannot be re-derived — where the drive pointed — so this is a single forward
 * pass rather than a second shooting solve, and the arc drawn is exactly the arc
 * that was priced.
 *
 * Falls back to the chord for a route with no direction on it, which is one
 * built before this module answered in curves.
 */
function heldDrivePath(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	centerId: string,
	centralMu: number,
	samples: number
): PathGeometry | null {
	const from = elementsToState(departure.elements, route.departJd, centralMu);
	const to = elementsToState(target.elements, route.arriveJd, centralMu);
	if (!from || !to) return null;

	const burnDays = route.legs.find((leg) => leg.kind === 'boost')?.days;
	if (!route.thrustDir || route.constantThrust == null || burnDays === undefined) {
		return straightCrossing(from.r, to.r, route, centerId, departure.id, target.id, samples);
	}

	const points = sampleHeldDrive(
		from,
		{
			burnSeconds: burnDays * SEC_PER_DAY,
			coastSeconds: (route.legs.find((leg) => leg.kind === 'cruise')?.days ?? 0) * SEC_PER_DAY,
			flips: route.legs.some((leg) => leg.kind === 'brake'),
			thrustDir: [route.thrustDir[0], route.thrustDir[1], route.thrustDir[2]]
		},
		route.constantThrust / 1000,
		centralMu,
		Math.max(2, Math.round(samples / 2))
	);
	return flownCrossing(points, route, centerId, departure.id, target.id, from.r, to.r);
}

/** Points along a drawn spiral, and the most revolutions worth drawing. Past a
 *  few dozen loops there are not enough points left per revolution for the line
 *  to be one, and the honest picture is none. */
const SPIRAL_DRAW_STEPS = 1024;
const SPIRAL_MAX_REVOLUTIONS = 40;

/** Points along a stretch spent going round a body: enough to read as its orbit
 *  rather than as a chord across it. */
const RIDING_SAMPLES = 64;

/**
 * The stretch of trip spent at `body` between two dates, as the body's own path.
 *
 * Null when there is no stretch to draw. A spiral that takes an afternoon is a
 * point, and a flyby has no arrival spiral at all.
 */
function ridingWith(
	body: TravelBody,
	fromJd: number,
	toJd: number,
	centralMu: number,
	kind: PathArcKind
): PathArc | null {
	if (!(toJd > fromJd)) return null;
	const points: Vec3[] = [];
	const jds: number[] = [];
	for (let i = 0; i < RIDING_SAMPLES; i++) {
		const jd = fromJd + ((toJd - fromJd) * i) / (RIDING_SAMPLES - 1);
		const state = elementsToState(body.elements, jd, centralMu);
		if (!state) return null;
		points.push(state.r);
		jds.push(jd);
	}
	return { kind, points, jds, startJd: fromJd, endJd: toJd };
}

/** Rotate `v` about the unit axis `n` by `angle`, Rodrigues. */
function rotateAbout(v: Vec3, n: Vec3, angle: number): Vec3 {
	const cos = Math.cos(angle);
	const sin = Math.sin(angle);
	return add(add(scale(v, cos), scale(cross(n, v), sin)), scale(n, dot(n, v) * (1 - cos)));
}

/** Angle from `a` to `b` about `n`, radians in [0, 2π). */
function angleAbout(a: Vec3, b: Vec3, n: Vec3): number {
	const angle = Math.atan2(dot(cross(a, b), n), dot(a, b));
	return angle < 0 ? angle + Math.PI * 2 : angle;
}

/**
 * The crossing of a spiral route: the orbit slowly opening out from one body's
 * to the other's, over however many revolutions that takes.
 *
 * The radii and the angle come from the same transfer the route was priced with,
 * rebuilt rather than carried. What is imposed on top is the two ends: the model
 * matches circular orbits, and the bodies are on eccentric inclined ones, so the
 * drawn arc is stretched onto where they actually are — a correction of a few
 * percent, spread along the arc, against a picture that would otherwise miss the
 * planet it is a trip to.
 *
 * The two end spirals are drawn as the body's own path over the months they
 * take. They happen inside a sphere of influence, which at this scale is a dot —
 * but they are a third of the trip, and leaving them out stopped the craft dead
 * at the encounter while the clock ran on for another year.
 */
function spiralPath(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	centerId: string,
	centralMu: number
): PathGeometry | null {
	const rebuilt = rebuildSpiral(
		departure,
		target,
		route,
		{ arrivalMode: route.arrivalMode, centralMu },
		SPIRAL_DRAW_STEPS
	);
	if (!rebuilt) return null;
	const { transfer, startJd } = rebuilt;

	const revolutions = transfer.sweepRad / (Math.PI * 2);
	if (!(revolutions <= SPIRAL_MAX_REVOLUTIONS)) return null;

	const from = elementsToState(departure.elements, startJd, centralMu);
	const to = elementsToState(target.elements, route.arriveJd, centralMu);
	if (!from || !to) return null;

	const u0 = normalize(from.r);
	const u1 = normalize(to.r);
	const normal = normalize(cross(from.r, from.v));
	if (!(norm(u0) > 0) || !(norm(u1) > 0) || !(norm(normal) > 0)) return null;

	// The revolutions come from the model; which point of the last one the target
	// is at comes from the target. They agree to within a fraction of a turn —
	// that is what the departure date was solved for — so the drawn sweep is the
	// modelled one rounded onto the arrival.
	const closing = angleAbout(u0, u1, normal);
	const turns = Math.max(0, Math.round((transfer.sweepRad - closing) / (Math.PI * 2)));
	const sweep = closing + turns * Math.PI * 2;
	if (!(sweep > 0)) return null;

	// What is left over once the planar sweep has run: the two orbits are not in
	// the same plane, so the arc is turned out of the departure's as it goes.
	const planarEnd = rotateAbout(u0, normal, sweep);
	const tilt = Math.acos(Math.max(-1, Math.min(1, dot(planarEnd, u1))));
	const tiltAxis = normalize(cross(planarEnd, u1));

	const startRadius = norm(from.r);
	const endRadius = norm(to.r);
	const modelStart = transfer.radiiKm[0];
	const modelEnd = transfer.radiiKm[transfer.radiiKm.length - 1];
	if (!(modelStart > 0) || !(modelEnd > 0)) return null;

	const points: Vec3[] = [];
	const jds: number[] = [];
	const count = transfer.radiiKm.length;
	for (let i = 0; i < count; i++) {
		// Along the arc by angle, which is what both corrections are spread over.
		const along =
			transfer.sweepRad > 0 ? transfer.sweptRad[i] / transfer.sweepRad : i / (count - 1);
		let direction = rotateAbout(u0, normal, sweep * along);
		if (tilt > 0 && norm(tiltAxis) > 0) {
			direction = rotateAbout(direction, tiltAxis, tilt * along);
		}
		const stretch = (startRadius / modelStart) * (1 - along) + (endRadius / modelEnd) * along;
		points.push(scale(direction, transfer.radiiKm[i] * stretch));
		jds.push(startJd + transfer.elapsedDays[i]);
	}
	if (points.length < 2) return null;

	// Climbing out of one well and dropping into the other: the craft is going
	// round a body, and the body is going round the Sun, so what a heliocentric
	// picture can show of it is the body's own path over those months.
	const arcs: PathArc[] = [];
	const climb = ridingWith(departure, route.departJd, startJd, centralMu, 'spiral-out');
	if (climb) arcs.push(climb);
	arcs.push({ kind: 'spiral', points, jds, startJd, endJd: route.arriveJd });
	const drop = ridingWith(
		target,
		route.arriveJd,
		route.departJd + routeDurationDays(route),
		centralMu,
		'spiral-in'
	);
	if (drop) arcs.push(drop);

	return {
		centerId,
		arcs,
		stops: [
			{
				kind: 'departure',
				jd: route.departJd,
				r: arcs[0].points[0],
				bodyId: departure.id,
				dvKms: dvOf(route, ['spiral-out'])
			},
			{
				kind: 'arrival',
				jd: route.arriveJd,
				r: to.r,
				bodyId: target.id,
				dvKms: dvOf(route, ['spiral-in', 'descent'])
			}
		],
		meeting: { bodyId: target.id, jd: route.arriveJd, r: to.r }
	};
}

/** The sampled arc, cut into one drawable stretch per phase. */
function flownCrossing(
	samples: HeldDriveSample[],
	route: Route,
	centerId: string,
	departureId: string,
	targetId: string,
	startR: Vec3,
	endR: Vec3
): PathGeometry | null {
	if (samples.length < 2) return null;

	const arcs: PathArc[] = [];
	let run: HeldDriveSample[] = [samples[0]];
	const flush = () => {
		if (run.length < 2) return;
		arcs.push({
			kind: run[0].kind,
			points: run.map((sample) => sample.r),
			jds: run.map((sample) => route.departJd + sample.elapsed / SEC_PER_DAY),
			startJd: route.departJd + run[0].elapsed / SEC_PER_DAY,
			endJd: route.departJd + run[run.length - 1].elapsed / SEC_PER_DAY
		});
	};
	for (const sample of samples.slice(1)) {
		if (sample.kind !== run[run.length - 1].kind) {
			run.push({ ...sample, kind: run[run.length - 1].kind });
			flush();
			// The stretches share the state they meet at, so the next one opens on
			// the point the last one closed at.
			run = [{ ...sample }];
			continue;
		}
		run.push(sample);
	}
	flush();
	if (arcs.length === 0) return null;

	return {
		centerId,
		arcs,
		stops: [
			{
				kind: 'departure',
				jd: route.departJd,
				r: startR,
				bodyId: departureId,
				dvKms: dvOf(route, ['ascent', 'injection'])
			},
			{
				kind: 'arrival',
				jd: route.arriveJd,
				r: endR,
				bodyId: targetId,
				dvKms: dvOf(route, ['capture', 'descent'])
			}
		],
		meeting: { bodyId: targetId, jd: route.arriveJd, r: endR }
	};
}

/** The stretches of a held drive between two fixed points. */
function straightCrossing(
	start: Vec3,
	end: Vec3,
	route: Route,
	centerId: string,
	departureId: string,
	targetId: string,
	samples: number
): PathGeometry | null {
	const span = sub(end, start);
	if (!(norm(span) > 0)) return null;

	// Nothing to slow down for at a flyby, so the drive never flips and the
	// crossing is one arc. A coast between the burns is the other thing that
	// changes the shape of one, and both are read back off the legs.
	const flips = route.legs.some((leg) => leg.kind === 'brake');
	const boostDays = route.legs.find((leg) => leg.kind === 'boost')?.days ?? route.tofDays;
	const coastDays = route.legs.find((leg) => leg.kind === 'cruise')?.days ?? 0;
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
	// time is the square root of the distance. Braking is the same run backwards,
	// and a coast is the one stretch that is even in both.
	const accelerating = (along: number) => Math.sqrt(along);
	const braking = (along: number) => 1 - Math.sqrt(Math.max(0, 1 - along));
	const even = (along: number) => along;

	// Ground each stretch covers, in whatever units `boostDays` is in: ½at² under
	// thrust and vt while coasting. Only their shares of the total matter, so the
	// acceleration cancels and never has to be known here.
	const stretches: {
		kind: PathArcKind;
		reach: number;
		days: number;
		count: number;
		timeFraction: (along: number) => number;
	}[] = [
		{
			kind: 'boost',
			reach: (boostDays * boostDays) / 2,
			days: boostDays,
			count: flips ? half : samples,
			timeFraction: accelerating
		}
	];
	// Even in both space and time, so two points describe it exactly.
	if (coastDays > 0) {
		stretches.push({
			kind: 'cruise',
			reach: boostDays * coastDays,
			days: coastDays,
			count: 2,
			timeFraction: even
		});
	}
	if (flips) {
		stretches.push({
			kind: 'brake',
			reach: (boostDays * boostDays) / 2,
			days: boostDays,
			count: half,
			timeFraction: braking
		});
	}

	const reached = stretches.reduce((sum, stretch) => sum + stretch.reach, 0);
	if (!(reached > 0)) return null;

	const arcs: PathArc[] = [];
	let along = 0;
	let jd = route.departJd;
	for (const [index, stretch] of stretches.entries()) {
		// The last stretch is pinned to the far end rather than accumulated onto
		// it, so rounding cannot leave the arc short of the body it arrives at.
		const last = index === stretches.length - 1;
		const toT = last ? 1 : along + stretch.reach / reached;
		const endJd = last ? route.arriveJd : jd + stretch.days;
		arcs.push({
			kind: stretch.kind,
			...line(along, toT, stretch.count, jd, endJd, stretch.timeFraction),
			startJd: jd,
			endJd
		});
		along = toT;
		jd = endJd;
	}

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
): PathGeometry | null {
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
