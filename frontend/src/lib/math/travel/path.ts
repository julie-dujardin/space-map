/**
 * The shape a route has in space, as opposed to what it costs (`Route`: legs,
 * Δv, dates). Rebuilds the geometry from the same deterministic inputs the
 * route was priced from, so re-solving reproduces the priced arc exactly
 * without carrying it across the worker boundary.
 *
 * Everything is in the transfer frame: km, ecliptic J2000, centred on
 * `centerId` — bar an end drawn planet-frame, which says so via its own
 * `anchorId` (see {@link TrajectoryFrame}).
 */

import { AU_KM } from '$lib/math/units';
import { sphereOfInfluenceKm, type TravelBody } from './body';
import { CAPTURE_APOAPSIS_RADII, GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import { solveFlyby } from './flyby';
import { sampleHeldDrive, samplePoweredFlight, type HeldDriveSample } from './held-drive';
import { solveLambert } from './lambert';
import { rebuildSpiral } from './low-thrust';
import {
	aeroPassRadiusKm,
	endArrivalOrbit,
	endDepartureOrbit,
	parkingOrbit,
	parkingRadiusKm,
	type EndOrbit
} from './maneuvers';
import { propagateState } from './propagate';
import {
	orbitChangeEnds,
	routeDurationDays,
	type Route,
	type RouteLeg,
	type RouteOptions
} from './route';
import { elementsToState } from './state';
import { relativeState, solveRadialArc, type RadialArc } from './system-transfer';
import { add, cross, dot, norm, normalize, scale, sub, type Vec3 } from './vec3';

/** A point on the trip worth marking: burns and encounters, not every leg —
 *  an ascent and its injection happen in the same place, so one marker does. */
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
 * How a stretch of the trip is flown. `cruise` coasts; `boost`/`brake` are the
 * halves of a held drive; `spiral` is a low-thrust crossing, with `spiral-out`/
 * `spiral-in` drawn as the body's own path since a spiral is thousands of
 * loops inside a dot at transfer scale.
 */
export type PathArcKind = 'cruise' | 'boost' | 'brake' | 'spiral' | 'spiral-out' | 'spiral-in';

export interface PathArc {
	kind: PathArcKind;
	/** Positions in the transfer frame, km, in flight order. */
	points: Vec3[];
	/**
	 * When each of `points` is passed, JD. Same length, increasing. Carried
	 * rather than inferred from the index: only a coasting arc is sampled evenly
	 * in time — a held drive is even along its line, a system transfer even in
	 * true anomaly.
	 */
	jds: number[];
	startJd: number;
	endJd: number;
}

/**
 * Which frame the ends of a trip are drawn in — a choice that cannot be had
 * both ways. Between the sphere of influence and periapsis the craft is on two
 * curves at once: a hyperbola about the body, and a worldline about the Sun,
 * which differ by the body's own motion (three million km over a Mars
 * capture's day and a half — wider than its sphere of influence).
 *
 * - `interplanetary` measures from the crossing's own centre: the passage
 *   carries on from the crossing exactly, and the end orbit draws as the
 *   trochoid it really is rather than a closed ring.
 * - `planetary` measures each end from its own body, held still: the passage
 *   is the bare hyperbola and the orbit closes, but the crossing outside
 *   cannot follow and fades out before the two would visibly disagree.
 */
export type TrajectoryFrame = 'interplanetary' | 'planetary';

/**
 * An end of a trip, drawn round the body it happens at: the orbit the craft is
 * in there, and the passage between that orbit and the crossing. A launch or
 * landing carries the line on to the ground, since pricing routes both through
 * the parking orbit too. Only a flyby ends nowhere.
 */
export interface EndOrbitPath {
	at: 'departure' | 'arrival';
	bodyId: string;
	/**
	 * What `points` and `approach` are measured from — the path's own centre when
	 * `interplanetary`, this end's `bodyId` when `planetary`. Not a translation
	 * the renderer could apply itself: a planet-frame end holds still round
	 * wherever the body is *now*, where an interplanetary one sits frozen at the
	 * encounter.
	 */
	anchorId: string;
	/** The orbit, closed or trochoid by frame, km. */
	points: Vec3[];
	/**
	 * The escape or capture between the sphere of influence and the orbit's
	 * periapsis, in flight order and the same frame, sharing periapsis with the
	 * orbit so the two meet along one tangent. At a surface end it keeps going:
	 * the ground leg (coast to the deorbit point plus the half-ellipse to the
	 * site, or the reverse) is part of this line rather than its own ring. A held
	 * drive climbs out under thrust rather than along an asymptote, so its
	 * departure is flown instead of derived; its arrival is the ordinary conic
	 * the capture was priced against. Empty where there is no passage at all: a
	 * spiral is under thrust the whole way, and an in-system transfer never
	 * escapes the primary's parking orbit.
	 */
	approach: Vec3[];
	/** When each of `approach` is passed, JD. Same length, increasing, but not
	 *  evenly spaced — the steps crowd at periapsis. */
	jds: number[];
	/**
	 * The stretch of the crossing this passage replaces, as a half-open range of
	 * sample indices into the arc that meets this body — the drawer keeps only
	 * `[trimFrom, trimTo)` and lets `approach` finish it, or the arc would run to
	 * the body's centre and cut through the orbit round it. The full range where
	 * there is nothing to replace.
	 */
	trimFrom: number;
	trimTo: number;
	/**
	 * The body's centre in the *transfer* frame, km — where the encounter
	 * happens, regardless of which frame the end is drawn in. Planet-frame, the
	 * drawn orbit no longer sits here; it's round the body wherever it is now.
	 */
	center: Vec3;
	/**
	 * The date the craft is at this end's periapsis, matching where `center`
	 * places the body. At a departure this is the route's own date (the
	 * injection burn); at an arrival it's solved, since the crossing was priced
	 * to the body's centre — a place the craft never goes — and real periapsis
	 * comes hours earlier.
	 */
	periJd: number;
	/** The orbit's widest radius, km — the orbit's own size, not the drawn
	 *  line's, so a trochoid smeared over millions of km still reads as the same
	 *  small orbit not worth drawing at system scale. */
	radiusKm: number;
	/** When the craft passes each of `points`, JD — the one revolution after it
	 *  settles into an arrival orbit, or before it leaves a departure one. What
	 *  lets a reader keep the craft on the orbit past the trip's own line.
	 *  Absent without a μ to date the revolution. */
	pointJds?: number[];
	/** When the craft is on the ground at this end — touchdown, or liftoff. Only
	 *  at a surface end, whose `approach` runs all the way to it. */
	surfaceJd?: number;
	/** The stretches of `approach` inside the rendered atmosphere — the ground
	 *  leg, and every dip an aero arrival flies below the shell — as half-open
	 *  index ranges in order, so they can be composited under the atmosphere's
	 *  glow instead of erased by it. */
	ground?: { from: number; to: number }[];
}

export interface TrajectoryPath {
	/** The body every position here is measured from, bar an end that says
	 *  otherwise with its own `anchorId`. */
	centerId: string;
	/** Which frame the ends are drawn in. The crossing is always the centre's. */
	frame: TrajectoryFrame;
	arcs: PathArc[];
	stops: PathStop[];
	/** The orbits at either end, where those ends are orbits. */
	endOrbits: EndOrbitPath[];
	/** Sphere-of-influence radius, km, per body the trip calls at. The scene
	 *  flips in-system by moon orbits, and this is its reach for a moonless end. */
	soiKm: Record<string, number>;
	/** Where the destination is at the moment the craft gets there — without it,
	 *  an arc ending nowhere near today's position reads as missing. */
	meeting: { bodyId: string; jd: number; r: Vec3 };
}

/** Somewhere on the drawn trajectory to look at. */
export interface PathViewpoint {
	/** Position, km, measured from `centerId` — the path's own centre unless a
	 *  planet-frame end anchors the spot to its body instead. */
	r: Vec3;
	/** Set when the spot is measured from somewhere other than the path's centre. */
	centerId?: string;
}

/**
 * Where to point the camera for the stretch of trip between `startJd` and
 * `endJd`. An instant (the two equal) lands on the stop or arc end it names; a
 * stretch lands mid-arc, the one place the whole of it is in view. Deliberately
 * not "where the craft is at a given moment" — samples aren't evenly timed
 * across arc kinds, and the camera wants a place on the line, not a claim
 * about the craft.
 */
export function pathViewpoint(
	path: TrajectoryPath,
	startJd: number,
	endJd: number
): PathViewpoint | null {
	if (path.arcs.length === 0) return null;

	// A stretch: the arc alongside it, or failing an exact match, the one its
	// middle falls inside. Spiral ends are skipped — framing a body's own orbit
	// would point the camera anywhere but at the body the craft is circling.
	if (endJd > startJd) {
		const middle = (startJd + endJd) / 2;
		const crossings = path.arcs.filter((a) => a.kind !== 'spiral-out' && a.kind !== 'spiral-in');
		const arc =
			crossings.find((a) => a.startJd <= startJd + 1e-6 && a.endJd >= endJd - 1e-6) ??
			crossings.find((a) => a.startJd <= middle && a.endJd >= middle);
		if (arc) return { r: arc.points[Math.floor(arc.points.length / 2)] };
		// Past the last arc there can still be trip: an aerobraking campaign is
		// flown on the arrival end's own line, after the crossing is over.
		const arrival = path.endOrbits.find((end) => end.at === 'arrival');
		if (arrival && arrival.jds.length > 0 && middle >= arrival.jds[0]) {
			let i = arrival.jds.length - 1;
			while (i > 0 && arrival.jds[i] > middle) i--;
			return { r: arrival.approach[i], centerId: arrival.anchorId };
		}
		return null;
	}

	// A surface end owns its instant: the nearby stop is the body's centre at the
	// *priced* date, which the live planet has since moved on from.
	const ground = path.endOrbits.find(
		(end) =>
			end.surfaceJd !== undefined &&
			Math.abs(end.surfaceJd - startJd) < 1e-6 &&
			end.approach.length > 0
	);
	if (ground) {
		return {
			r: ground.approach[ground.at === 'departure' ? 0 : ground.approach.length - 1],
			centerId: ground.anchorId
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
	return { r };
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
	/** Which frame to draw the ends in. Defaults to `interplanetary`, which is the
	 *  frame the crossing itself is in and the only one that joins onto it. */
	frame?: TrajectoryFrame;
	/**
	 * Where a surface end touches its body: the site's position from the body's
	 * centre, km, in the transfer frame's axes, at a given date. A function of
	 * time because the body spins under the trip — read at the touchdown/liftoff
	 * the geometry works out, not the priced date — which keeps rotation models
	 * out of the kernel; the caller owns them. Without one, a landing still
	 * reaches the ground (opposite periapsis in its own plane), just unaimed.
	 */
	surfaceSites?: {
		departure?: (jd: number) => Vec3 | null;
		arrival?: (jd: number) => Vec3 | null;
	};
}

const DEFAULT_SAMPLES = 180;

/** Δv of every leg of `kinds`, km/s. */
function dvOf(route: Route, kinds: readonly string[]): number {
	return route.legs.reduce((sum, leg) => (kinds.includes(leg.kind) ? sum + leg.dvKms : sum), 0);
}

/**
 * Sample the conic through `r`/`v` over `days`. Endpoints are placed exactly
 * rather than propagated to — they're where the route was solved against, and
 * a propagator that drifts a few km over a year shouldn't move the marker off
 * the planet.
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

/** The coast from `r`/`v` to `endpoint`, sampled as an arc. */
function conicArc(
	r: Vec3,
	v: Vec3,
	endpoint: Vec3,
	startJd: number,
	days: number,
	mu: number,
	samples: number
): PathArc | null {
	const points = sampleConic(r, v, days, mu, samples, endpoint);
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
	return conicArc(from.r, arc.v1, to.r, startJd, days, mu, samples);
}

/** The stretch of `arc` from sample `from` up to `to`, half-open. */
function trimmedArc(arc: PathArc, from: number, to: number): PathArc {
	const points = arc.points.slice(from, to);
	const jds = arc.jds.slice(from, to);
	return { ...arc, points, jds, startJd: jds[0], endJd: jds[jds.length - 1] };
}

/** A trajectory before the orbits at its ends are hung off it — what each of the
 *  builders below answers with. */
type PathGeometry = Omit<TrajectoryPath, 'endOrbits' | 'frame' | 'soiKm'>;

/**
 * Rebuild the geometry of `route`. Null when the arc can't be reproduced — a
 * swing-by whose via body wasn't supplied, or a solve that no longer converges
 * — since a straight line between the ends wouldn't be the route.
 */
export function buildTrajectoryPath(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions
): TrajectoryPath | null {
	const path = buildCrossing(departure, target, route, options);
	if (!path) return null;
	const frame = options.frame ?? 'interplanetary';
	const endOrbits = endOrbitPaths(departure, target, route, options, path);
	const soiKm: Record<string, number> = {};
	for (const body of [departure, target, ...(options.vias ?? [])]) {
		const soi = sphereOfInfluenceKm(
			body,
			options.centralMu ?? GM_SUN_KM3_S2,
			Math.abs(body.elements.a) * AU_KM
		);
		if (Number.isFinite(soi)) soiKm[body.id] = soi;
	}
	// An arrival passage re-dates the encounter, so the meeting follows it or it
	// would mark a spot the body has already left. Stops stay priced — they're
	// where the arcs end, which is where the scrubbed craft ends up.
	const arrival = endOrbits.find((end) => end.at === 'arrival' && end.approach.length > 0);
	if (!arrival) return { ...path, frame, endOrbits, soiKm };
	return {
		...path,
		frame,
		meeting: { ...path.meeting, jd: arrival.periJd, r: arrival.center },
		endOrbits,
		soiKm
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
		orbitChange,
		vias = [],
		samples = DEFAULT_SAMPLES
	} = options;

	if (orbitChange) return orbitChangePath(departure, route, centerId, samples);
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
		dvKms: dvOf(route, ['capture', 'raise', 'descent'])
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
		const out = solveLambert(from.r, mid.r, tof1 * SEC_PER_DAY, centralMu, retrograde);
		const back = solveLambert(mid.r, to.r, tof2 * SEC_PER_DAY, centralMu, retrograde);
		if (!out || !back) return null;
		const first = conicArc(from.r, out.v1, mid.r, route.departJd, tof1, centralMu, samples);
		const second = conicArc(mid.r, back.v1, to.r, flyby.jd, tof2, centralMu, samples);
		if (!first || !second) return null;

		// The two arcs were solved to the body's centre, a place the craft never
		// goes — really it flies the priced hyperbola. Replaces the corner where
		// that can be rebuilt; otherwise (a pass at the sphere's edge, really a
		// burn) the corner is the truer picture.
		const passage = assistPassage({
			via,
			mid,
			vIn: out.v2,
			vOut: back.v1,
			first,
			second,
			flybyJd: flyby.jd,
			centralMu
		});
		const arcs = passage
			? [
					trimmedArc(first, 0, passage.cutIn + 1),
					{
						kind: 'cruise' as const,
						points: passage.points,
						jds: passage.jds,
						startJd: passage.jds[0],
						endJd: passage.jds[passage.jds.length - 1]
					},
					trimmedArc(second, passage.cutOut, second.points.length)
				]
			: [first, second];

		return {
			centerId,
			arcs,
			stops: [
				departureStop,
				{
					kind: 'assist',
					jd: flyby.jd,
					// The burn is made at periapsis, so that is where the dot belongs —
					// the centre is only where the pricing had to put it.
					r: passage?.peri ?? mid.r,
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
 * The orbits at the ends of a trip, and the passages joining them to the
 * crossing. Both sit where the body is at that end's periapsis date — the
 * route's own date at a departure, solved by the passage at an arrival (which
 * knows where the crossing really left off).
 *
 * Patched conics, drawn as flown: the two radii and excess speed are fixed by
 * pricing; the plane is free, taken as near the arc's own plane as an
 * asymptote allows so the passage reads as that line continuing. Where there
 * is a passage it also fixes the orbit's low point, since the insertion burn
 * happens there and the two curves should meet along the same tangent.
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

	const { centralMu = GM_SUN_KM3_S2, systemPrimary, frame = 'interplanetary' } = options;
	// What each end body's sphere of influence is measured against: the primary
	// inside one system, the Sun elsewhere.
	const primaryMu =
		options.orbitChange || systemPrimary
			? (systemPrimary === 'target' ? target : departure).mu
			: centralMu;
	const approaches = endApproaches(departure, target, route, options, path);

	const orbits: EndOrbitPath[] = [];
	const sites = options.surfaceSites ?? {};
	// A launch/landing is priced through the parking orbit, so a surface end
	// takes that orbit and carries the line on to the ground.
	const fromGround = route.departureMode === 'surface';
	const from = endDepartureOrbit(departure, route.departureMode, route.departureOrbit);
	if (from || fromGround) {
		orbits.push(
			endOrbitPath({
				at: 'departure',
				body: departure,
				center: centers.from,
				orbit: from ?? parkingOrbit(departure),
				arc: first,
				periJd: route.departJd,
				approach: approaches.from,
				primaryMu,
				frame,
				centerId: path.centerId,
				surface: fromGround ? { siteAt: sites.departure } : undefined
			})
		);
	}
	const toGround = route.arrivalMode === 'landing';
	const to = endArrivalOrbit(target, route.arrivalMode, route.targetOrbit);
	if (to || toGround) {
		orbits.push(
			endOrbitPath({
				at: 'arrival',
				body: target,
				center: centers.to,
				orbit: to ?? parkingOrbit(target),
				arc: last,
				periJd: route.arriveJd,
				approach: approaches.to,
				primaryMu,
				frame,
				centerId: path.centerId,
				surface: toGround ? { siteAt: sites.arrival } : undefined,
				aero: arrivalAero(target, route)
			})
		);
	}
	return orbits;
}

/**
 * How the craft meets each end body, re-solved rather than carried, like the
 * arcs themselves. The body comes as a function of time, not a frozen state,
 * because the passage needs it twice: {@link soiCrossingJd} chases it to find
 * where the crossing really enters the sphere of influence, and
 * {@link hyperbolicPassage} carries its true displacement so the drawn line is
 * the patched-conic worldline, not a straight-line stand-in.
 *
 * Absent wherever there's no passage to draw: a spiral crosses under thrust
 * the whole way, and inside one system the transfer ellipse already leaves its
 * parking orbit at periapsis, tangent to the arc with nothing in between.
 */
interface EndApproach {
	/** Excess velocity, km/s: the craft's own less the body's. Zero at an end
	 *  climbed out of under thrust, which has no asymptote to fall along. */
	vInf: Vec3;
	/** The body's position at `jd` in the transfer frame, km. */
	bodyAt: (jd: number) => Vec3 | null;
	/** Where the crossing puts the craft at a date, km — chased to find where it
	 *  really crosses the sphere of influence. A conic for a coasting route; a
	 *  held drive is under thrust, so it reads its own flown samples instead. */
	craftAt: (jd: number) => Vec3 | null;
	/** This end's priced date, where that chase starts. */
	jd: number;
	/** Set where the craft leaves under thrust rather than on a conic: the
	 *  drive's inertial direction and what it holds, km/s². */
	drive?: { dir: Vec3; accelKmS2: number };
}

/** Where the crossing conic puts the craft, for the ends flown on one. */
function conicCraftAt(
	craft: { r: Vec3; v: Vec3; jd: number },
	mu: number
): (jd: number) => Vec3 | null {
	return (jd) => propagateState(craft.r, craft.v, (jd - craft.jd) * SEC_PER_DAY, mu);
}

function endApproaches(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions,
	path: PathGeometry
): { from?: EndApproach; to?: EndApproach } {
	const { centralMu = GM_SUN_KM3_S2, retrograde = false, systemPrimary, vias = [] } = options;
	if (route.lowThrust) return {};
	if (route.constantThrust != null) {
		return heldDriveApproaches(departure, target, route, options, path);
	}
	// A trip that stays at one body crosses no sphere of influence, so neither
	// end is approached from outside one.
	if (options.orbitChange) return {};

	if (systemPrimary) {
		// Only the way out: coming home, pricing uses the *outward* leg's excess
		// speed at the satellite, not the drawn arc's own — and this module never
		// draws a shape it isn't pricing.
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
		// The arc's velocity at the satellite, rebuilt from the two components it
		// was solved in: climbing, and going round.
		const outward = normalize(state.r);
		const along = normalize(cross(normal, outward));
		const vArc = add(scale(outward, arc.vFarRadialKms), scale(along, arc.vFarTangentialKms));
		return {
			to: {
				vInf: sub(vArc, state.v),
				bodyAt: (jd) => relativeState(target, departure, jd)?.r ?? null,
				craftAt: conicCraftAt({ r: state.r, v: vArc, jd: route.arriveJd }, departure.mu),
				jd: route.arriveJd
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
				craftAt: conicCraftAt({ r: from.r, v: out.v1, jd: route.departJd }, centralMu),
				jd: route.departJd
			},
			to: {
				vInf: sub(back.v2, to.v),
				bodyAt: targetAt,
				craftAt: conicCraftAt({ r: to.r, v: back.v2, jd: route.arriveJd }, centralMu),
				jd: route.arriveJd
			}
		};
	}

	const arc = solveLambert(from.r, to.r, route.tofDays * SEC_PER_DAY, centralMu, retrograde);
	if (!arc) return {};
	return {
		from: {
			vInf: sub(arc.v1, from.v),
			bodyAt: departureAt,
			craftAt: conicCraftAt({ r: from.r, v: arc.v1, jd: route.departJd }, centralMu),
			jd: route.departJd
		},
		to: {
			vInf: sub(arc.v2, to.v),
			bodyAt: targetAt,
			craftAt: conicCraftAt({ r: to.r, v: arc.v2, jd: route.arriveJd }, centralMu),
			jd: route.arriveJd
		}
	};
}

/** Where the drawn crossing puts the craft at `jd`, read between the samples it
 *  was flown at. What stands in for a conic where there isn't one: a held drive
 *  is under thrust, so nothing closed-form follows it. */
function arcCraftAt(arcs: readonly PathArc[]): (jd: number) => Vec3 | null {
	const jds: number[] = [];
	const points: Vec3[] = [];
	for (const arc of arcs) {
		for (let i = 0; i < arc.jds.length; i++) {
			// Neighbouring stretches share the state they meet at.
			if (jds.length > 0 && arc.jds[i] <= jds[jds.length - 1]) continue;
			jds.push(arc.jds[i]);
			points.push(arc.points[i]);
		}
	}
	return (jd) => {
		if (jds.length < 2 || jd < jds[0] || jd > jds[jds.length - 1]) return null;
		let hi = 1;
		while (hi < jds.length - 1 && jds[hi] < jd) hi++;
		const span = jds[hi] - jds[hi - 1];
		const along = span > 0 ? (jd - jds[hi - 1]) / span : 0;
		return add(points[hi - 1], scale(sub(points[hi], points[hi - 1]), along));
	};
}

/**
 * How a held drive meets each end. The two are not the same shape because the
 * pricing is not: the ship climbs out of the first well under thrust at no
 * excess speed at all, and falls into the second carrying whatever the crossing
 * left it with, paying an ordinary capture for it. So the departure is flown
 * and the arrival is the conic that capture was priced against.
 *
 * The arrival's excess speed is the route's own; only its *direction* is read
 * off the crossing, from the last step it takes against the body's motion over
 * the same moment.
 */
function heldDriveApproaches(
	departure: TravelBody,
	target: TravelBody,
	route: Route,
	options: PathOptions,
	path: PathGeometry
): { from?: EndApproach; to?: EndApproach } {
	const { centralMu = GM_SUN_KM3_S2, systemPrimary } = options;
	const last = path.arcs[path.arcs.length - 1];
	if (route.constantThrust == null || !last || last.points.length < 2) return {};
	// Inside one system the crossing already runs between the primary's parking
	// orbit and the satellite, so only the satellite is met from outside a
	// sphere of influence — and coming home it is left rather than met.
	if (systemPrimary === 'target') return {};
	const inSystem = systemPrimary === 'departure';
	const targetAt = inSystem
		? (jd: number) => relativeState(target, departure, jd)?.r ?? null
		: (jd: number) => elementsToState(target.elements, jd, centralMu)?.r ?? null;
	const craftAt = arcCraftAt(path.arcs);

	const from: EndApproach | undefined =
		inSystem || !route.thrustDir
			? undefined
			: {
					vInf: [0, 0, 0],
					bodyAt: (jd) => elementsToState(departure.elements, jd, centralMu)?.r ?? null,
					craftAt,
					jd: route.departJd,
					drive: {
						dir: [route.thrustDir[0], route.thrustDir[1], route.thrustDir[2]],
						accelKmS2: route.constantThrust / 1000
					}
				};

	const count = last.points.length;
	const before = targetAt(last.jds[count - 2]);
	const after = targetAt(last.jds[count - 1]);
	if (!before || !after) return { from };
	const step = sub(sub(last.points[count - 1], last.points[count - 2]), sub(after, before));
	if (!(norm(step) > 0) || !(route.vInfArrKms > 0)) return { from };
	return {
		from,
		to: {
			vInf: scale(normalize(step), route.vInfArrKms),
			bodyAt: targetAt,
			craftAt,
			jd: route.arriveJd
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
	// Both ends are the body the frame is centred on, so both are the origin.
	if (options.orbitChange) return { from: [0, 0, 0], to: [0, 0, 0] };
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
 * Plane and direction of travel come from the two samples of the crossing
 * nearest this body, in flight order — without an approach, that's all there
 * is, and the orbit's low point is put on the side the craft comes from.
 *
 * `arc` is the stretch of crossing meeting this body; `periJd` is the route's
 * date for this end, which the passage may re-date, and the crossing's last
 * step is cut against whichever date stands.
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
	frame: TrajectoryFrame;
	centerId: string;
	/** Present when this end is the ground rather than the orbit — the trip still
	 *  passes through the orbit, and the drawn line carries on to the site. */
	surface?: { siteAt?: (jd: number) => Vec3 | null };
	/** How the atmosphere takes part in an aero-assisted arrival. */
	aero?: AeroArrival;
}): EndOrbitPath {
	const { at, body, center, orbit, arc, periJd, approach, primaryMu, frame, centerId, surface } =
		end;
	// The atmosphere's part of the arrival hangs off the pass, so with no
	// passage to place it on the end draws as if unassisted.
	const aero = at === 'arrival' && approach ? end.aero : undefined;
	const outward = at === 'departure';
	const count = arc.points.length;
	// A satellite in a heliocentric plan flies on borrowed elements, so the
	// priced centre is its ancestor's position, nowhere near the body itself.
	// Drawn off the live body instead, planet-frame style — the passage still
	// holds wherever the body actually is.
	const anchored = frame === 'planetary' || body.borrowedElements === true;
	// The two samples this end meets the body at, in flight order.
	const a = outward ? arc.points[0] : arc.points[count - 2];
	const b = outward ? arc.points[1] : arc.points[count - 1];
	// The ecliptic's own normal for an arc with no plane to read — two samples on
	// top of each other, or a radial arc seen exactly edge on.
	const crossed = cross(a, b);
	const arcNormal = norm(crossed) > 0 ? normalize(crossed) : ([0, 0, 1] as Vec3);

	// An aerocaptured arrival never burns at the orbit's periapsis: the pass
	// itself is the insertion, flown at the entry interface.
	const rPassKm = aero?.mode === 'aerocapture' ? aero.rEntryKm : orbit.rPeriKm;
	const passageOf = (planeHint?: Vec3) => {
		if (!approach) return null;
		// An end left under thrust has no asymptote to fall along, so it is flown
		// out rather than derived.
		const drive = approach.drive;
		return drive && outward
			? poweredEscape({
					body,
					approach,
					drive,
					rPeriKm: rPassKm,
					arcNormal,
					primaryMu,
					arc,
					endJd: periJd,
					frame,
					planeHint
				})
			: hyperbolicPassage({
					body,
					approach,
					rPeriKm: rPassKm,
					arcNormal,
					at,
					primaryMu,
					center,
					arc,
					endJd: periJd,
					frame,
					planeHint
				});
	};
	let passage = passageOf();
	// A landing is aimed somewhere, so the plane's free choice is spent holding
	// the site rather than the crossing's own plane. Read at a rough touchdown;
	// the ground leg re-reads it exactly and works off-plane residue out along
	// the descent.
	if (surface?.siteAt && passage) {
		const halfDays =
			(Math.PI * Math.sqrt(((rPassKm + body.radiusKm) / 2) ** 3 / body.mu)) / SEC_PER_DAY;
		const roughDays = halfDays + (aero?.campaignDays ?? 0);
		const site = surface.siteAt(passage.periJd + (outward ? -roughDays : roughDays));
		if (site && norm(site) > 0) passage = passageOf(normalize(site)) ?? passage;
	}
	const normal = passage?.normal ?? arcNormal;
	const periapsis = passage?.periapsis ?? approachSide(arcNormal, a, b);
	// A passage re-dates its end, and the encounter is where the body then is;
	// without one the priced date stands.
	const ringCenter = passage?.center ?? center;
	const endPeriJd = passage?.periJd ?? periJd;

	// An anchored end measures everything straight off its body; otherwise it all
	// hangs where the encounter puts the body, which is somewhere along the
	// crossing.
	const origin: Vec3 = anchored ? [0, 0, 0] : ringCenter;

	// Direct entry: the pass that would have captured the craft puts it on the
	// ground instead, so the ground leg falls straight from the entry interface
	// with no parking coast in between.
	const directEntry = aero?.mode === 'aerocapture' && surface != null && passage != null;
	const aeroLegs =
		aero && passage && !directEntry
			? aeroArrivalLegs({ aero, body, orbit, normal, periapsis, periJd: endPeriJd })
			: null;
	// Everything inward of an aerobraking pass is frozen where the body was at
	// the encounter: the campaign lasts months, and carrying the body's real
	// motion would smear the revolutions over half its orbit. The seam is safe —
	// the passage's carried offset is zero at periapsis by construction.
	const frozen = aeroLegs != null;

	const ground = surface
		? surfaceLeg({
				outward,
				body,
				rParkKm: directEntry && aero ? aero.rEntryKm : orbit.rPeriKm,
				normal,
				// After a campaign the craft leaves from the final apoapsis, on the
				// far side of the line of apsides from where the passage came in.
				periapsis: aeroLegs ? scale(periapsis, -1) : periapsis,
				periJd: aeroLegs?.endJd ?? endPeriJd,
				siteAt: surface.siteAt,
				bodyAt: anchored || frozen ? undefined : approach?.bodyAt,
				center: ringCenter,
				includePeriapsis: !passage && !aeroLegs
			})
		: null;

	// The passage and the ground stretch are one line, in flight order: up off the
	// ground and out, or in and down onto it. Both own their boundary sample when
	// the coast between them vanishes, so the seam drops whichever date repeats.
	const approachPoints: Vec3[] = [];
	const approachJds: number[] = [];
	let groundKept = 0;
	const append = (part: { points: Vec3[]; jds: number[] } | null, isGround = false) => {
		if (!part) return;
		for (let i = 0; i < part.points.length; i++) {
			const jd = part.jds[i];
			if (approachJds.length > 0 && jd <= approachJds[approachJds.length - 1] + 1e-9) continue;
			approachPoints.push(add(origin, part.points[i]));
			approachJds.push(jd);
			if (isGround) groundKept++;
		}
	};
	if (outward) {
		append(ground, true);
		append(passage);
	} else {
		append(passage);
		append(aeroLegs);
		append(ground, true);
	}
	const groundRanges =
		ground && groundKept > 0
			? outward
				? [{ from: 0, to: groundKept }]
				: [{ from: approachPoints.length - groundKept, to: approachPoints.length }]
			: [];
	const airRanges = aero
		? underShell(groundRanges, approachPoints, origin, body, aero)
		: groundRanges;

	// A surface end with no passage still owns the last of its crossing, or the
	// arc would run through the body's centre and the ground stretch that
	// finishes the trip. A passage-less borrowed end is left alone instead — its
	// radius is measured about the ancestor, and the arc is right to run there.
	const borrowed = body.borrowedElements === true;
	const trimFrom =
		passage && outward
			? passage.cut
			: ground && outward && !borrowed
				? radiusCut(arc, ringCenter, orbit.rPeriKm, outward)
				: 0;
	const trimTo =
		passage && !outward
			? passage.cut + 1
			: ground && !outward && !borrowed
				? radiusCut(arc, ringCenter, orbit.rPeriKm, outward)
				: count;

	// An aero arrival meets its orbit at apoapsis, so the revolution's own
	// clock starts half a period later, at the first periapsis it settles on.
	const halfOrbitDays =
		body.mu > 0
			? (Math.PI * Math.sqrt(((orbit.rPeriKm + orbit.rApoKm) / 2) ** 3 / body.mu)) / SEC_PER_DAY
			: 0;
	// A surface end draws no ring of its own: the stretch of orbit the trip
	// actually rides is part of the line above.
	const ring = surface
		? null
		: orbitRing({
				origin,
				orbit,
				normal,
				periapsis,
				mu: body.mu,
				periJd: aeroLegs ? aeroLegs.endJd + halfOrbitDays : endPeriJd,
				// A closed ring is only closed in the body's own frame; elsewhere it
				// needs the body's motion. An end with no passage has no way to ask for
				// it — and an aero arrival's is frozen with the rest of its campaign —
				// so it closes anyway and stays honest only by being small.
				bodyAt: anchored || frozen ? undefined : approach?.bodyAt,
				center: ringCenter,
				outward
			});

	return {
		at,
		bodyId: body.id,
		anchorId: anchored ? body.id : centerId,
		points: ring?.points ?? [],
		pointJds: ring?.jds,
		approach: approachPoints,
		jds: approachJds,
		trimFrom,
		trimTo,
		center: ringCenter,
		periJd: endPeriJd,
		radiusKm: orbit.rApoKm,
		surfaceJd: ground?.groundJd,
		ground: airRanges.length > 0 ? airRanges : undefined
	};
}

/**
 * Where the crossing gives way to a surface end with no passage: its last
 * sample still outside the parking orbit. Past that radius the two-body solve
 * would cut the arc straight through the ground leg drawn over it.
 */
function radiusCut(arc: PathArc, center: Vec3, rKm: number, outward: boolean): number {
	const count = arc.points.length;
	if (outward) {
		for (let i = 0; i < count; i++) {
			if (norm(sub(arc.points[i], center)) > rKm) return Math.min(i, count - 2);
		}
		return 0;
	}
	for (let i = count - 1; i >= 0; i--) {
		if (norm(sub(arc.points[i], center)) > rKm) return Math.max(i + 1, 2);
	}
	return count;
}

/**
 * How the atmosphere takes part in an arrival, read off the priced route — the
 * geometry is re-derived from the same terms the pricing used, never carried.
 */
interface AeroArrival {
	mode: 'aerocapture' | 'aerobraking';
	/** Radius the braking pass is flown at, km. */
	rEntryKm: number;
	/** Days the aerobraking campaign takes; zero for a single pass. */
	campaignDays: number;
	/** Apoapsis of the loose ellipse an aerobraking capture burn drops into, km. */
	rApoLooseKm: number;
	/** Altitude the rendered shell tops out at, km, when known. */
	shellTopKm?: number;
}

/** The aero part of a route's arrival, when the pricing actually flew one — a
 *  request the body ignored (no air, or a pass that wouldn't fit under the
 *  orbit) leaves the drawing propulsive too. */
function arrivalAero(body: TravelBody, route: Route): AeroArrival | undefined {
	if (route.aero === 'none' || !route.legs.some((leg: RouteLeg) => leg.aerobraked)) {
		return undefined;
	}
	return {
		mode: route.aero,
		rEntryKm: aeroPassRadiusKm(body),
		campaignDays: route.legs.find((leg) => leg.kind === 'aerobrake')?.days ?? 0,
		rApoLooseKm: CAPTURE_APOAPSIS_RADII * body.radiusKm,
		shellTopKm: body.aeroShellTopKm
	};
}

/** Fewest points per half revolution of an aero arrival's ellipses; the wide
 *  ones get more — a campaign's loose ellipse spans tens of radii on screen,
 *  where this few reads as a polygon. */
const AERO_HALF_SAMPLES = 32;
const AERO_HALF_SAMPLES_MAX = 128;

/** Points for half a revolution, scaled up with how far the ellipse reaches,
 *  so the wide ones stay as smooth per unit of screen as the small ones. */
function aeroHalfSamples(rp: number, ra: number): number {
	const scaled = Math.round(AERO_HALF_SAMPLES * Math.sqrt(ra / Math.max(rp, 1)));
	return Math.min(AERO_HALF_SAMPLES_MAX, Math.max(AERO_HALF_SAMPLES, scaled));
}
/** Drawn revolutions standing in for an aerobraking campaign's hundreds — one
 *  per few weeks of campaign, within reason. */
const AEROBRAKE_MIN_REVS = 4;
const AEROBRAKE_MAX_REVS = 10;

/**
 * What an aero arrival flies between the pass and the orbit it was priced
 * into, in flight order from the passage's periapsis, body-relative km.
 * Aerocapture: the post-pass ellipse out to apoapsis, where the trim burn
 * lifts periapsis clear of the air. Aerobraking: the loose capture ellipse out
 * to the walk-in, then drag's shrinking revolutions — a few drawn in place of
 * the real hundreds, spread over the campaign's true dates so a scrub rides
 * them. Every ellipse shares the line of apsides (drag at periapsis doesn't
 * turn it), so each seam lands on a shared apsis exactly.
 */
function aeroArrivalLegs(leg: {
	aero: AeroArrival;
	body: TravelBody;
	orbit: EndOrbit;
	normal: Vec3;
	periapsis: Vec3;
	periJd: number;
}): { points: Vec3[]; jds: number[]; endJd: number } | null {
	const { aero, body, orbit, normal, periapsis, periJd } = leg;
	if (!(body.mu > 0)) return null;
	const inPlane = normalize(cross(normal, periapsis));
	const points: Vec3[] = [];
	const jds: number[] = [];
	const put = (point: Vec3, jd: number) => {
		if (jds.length > 0 && jd <= jds[jds.length - 1] + 1e-9) return;
		points.push(point);
		jds.push(jd);
	};
	const halfPeriodDays = (rp: number, ra: number) =>
		Math.PI / Math.sqrt(body.mu / ((rp + ra) / 2) ** 3) / SEC_PER_DAY;
	// Half a revolution, dated by Kepler: periapsis to apoapsis, or apoapsis
	// down. Stepped in eccentric anomaly, whose parameterisation is a squashed
	// circle — even steps in true anomaly crowd the line's turning at periapsis
	// and leave the wide side as long straight chords. `stretch` rescales the
	// dates, standing a drawn revolution in for many real ones. Returns the
	// date at the far apsis.
	const half = (rp: number, ra: number, descending: boolean, jd0: number, stretch = 1) => {
		const a = (rp + ra) / 2;
		const e = (ra - rp) / (ra + rp);
		const b = a * Math.sqrt(1 - e * e);
		const meanMotion = Math.sqrt(body.mu / a ** 3);
		const fromPeri = (E: number) => (E - e * Math.sin(E)) / meanMotion / SEC_PER_DAY;
		const count = aeroHalfSamples(rp, ra);
		for (let i = 1; i <= count; i++) {
			const E = (descending ? Math.PI : 0) + (Math.PI * i) / count;
			const elapsed = fromPeri(E) - (descending ? fromPeri(Math.PI) : 0);
			put(
				add(scale(periapsis, a * (Math.cos(E) - e)), scale(inPlane, b * Math.sin(E))),
				jd0 + elapsed * stretch
			);
		}
		return jd0 + fromPeri(Math.PI) * stretch;
	};

	if (aero.mode === 'aerocapture') {
		// One pass leaves the craft on an ellipse whose periapsis is still in the
		// air; it coasts out to apoapsis, and the trim burn there hands over to
		// the priced orbit along their shared apsis.
		const endJd = half(aero.rEntryKm, orbit.rApoKm, false, periJd);
		return { points, jds, endJd };
	}

	// Aerobraking: the engine captured at the orbit's own periapsis into the
	// loose ellipse; the walk-in at its apoapsis drops periapsis into the air.
	const revs = Math.max(
		AEROBRAKE_MIN_REVS,
		Math.min(AEROBRAKE_MAX_REVS, Math.round(aero.campaignDays / 25))
	);
	const apoAt = (k: number) => aero.rApoLooseKm * (orbit.rApoKm / aero.rApoLooseKm) ** (k / revs);
	let natural = 0;
	for (let k = 0; k < revs; k++) {
		natural +=
			halfPeriodDays(aero.rEntryKm, apoAt(k)) + halfPeriodDays(aero.rEntryKm, apoAt(k + 1));
	}
	const stretch = natural > 0 && aero.campaignDays > 0 ? aero.campaignDays / natural : 1;
	let jd = half(orbit.rPeriKm, aero.rApoLooseKm, false, periJd);
	for (let k = 0; k < revs; k++) {
		jd = half(aero.rEntryKm, apoAt(k), true, jd, stretch);
		jd = half(aero.rEntryKm, apoAt(k + 1), false, jd, stretch);
	}
	// The walk-out at the final apoapsis lifts periapsis clear; the priced orbit
	// takes over from the same apsis.
	return { points, jds, endJd: jd };
}

/**
 * Where the drawn line is inside the rendered atmosphere: the ground stretch
 * it arrives holding, plus every dip an aero arrival flies below the shell —
 * which the overlay must composite under the glow, or the shell's depth write
 * erases them. Judged by radius, so a shell the pass skims above marks
 * nothing, which is right: that stretch isn't occluded either.
 */
function underShell(
	ranges: { from: number; to: number }[],
	points: readonly Vec3[],
	origin: Vec3,
	body: TravelBody,
	aero: AeroArrival
): { from: number; to: number }[] {
	const topKm = body.radiusKm + (aero.shellTopKm ?? 2 * (aero.rEntryKm - body.radiusKm));
	const inAir = new Array<boolean>(points.length).fill(false);
	for (const range of ranges) {
		for (let i = range.from; i < range.to; i++) inAir[i] = true;
	}
	// Carried motion inflates a sample's apparent radius, never shrinks it to
	// shell scale, so the test stays honest for the passage's outer reaches.
	for (let i = 0; i < points.length; i++) {
		if (norm(sub(points[i], origin)) < topKm) inAir[i] = true;
	}
	const merged: { from: number; to: number }[] = [];
	for (let i = 0; i < inAir.length; i++) {
		if (!inAir[i]) continue;
		const last = merged[merged.length - 1];
		if (last && last.to === i) last.to = i + 1;
		else merged.push({ from: i, to: i + 1 });
	}
	return merged;
}

/** Points down a ground leg's half-ellipse. Fewer than a ring: it is half of
 *  one, and its whole extent is a body's own scale. */
const DESCENT_SAMPLES = 48;

/**
 * The ground stretch of a surface end, in flight order, measured from the
 * body: coast round the parking orbit from periapsis to the deorbit point and
 * fall down the half-ellipse to the site, or the reverse on departure.
 *
 * The two radii are pricing's (parking orbit, body surface); the rest is a
 * drawing choice made as flown: the half-ellipse is tangent to the parking
 * orbit at the deorbit point and touches the ground at the site. The site
 * depends on the touchdown/liftoff date this geometry itself produces, so the
 * date is iterated to a fixpoint. A site off the orbit's plane is reached by
 * bending the fall out of plane — all the bend at the ground, none at the
 * deorbit point, which still has an orbit to be tangent to.
 *
 * Null with no ground to draw to: a parking radius not above the site, or a
 * body with no μ to date the fall.
 */
function surfaceLeg(leg: {
	outward: boolean;
	body: TravelBody;
	rParkKm: number;
	normal: Vec3;
	periapsis: Vec3;
	periJd: number;
	siteAt?: (jd: number) => Vec3 | null;
	bodyAt?: (jd: number) => Vec3 | null;
	center: Vec3;
	/** Whether the leg owns the periapsis sample — a passage already puts one
	 *  there, and two dates the same would stall anything reading the line. */
	includePeriapsis: boolean;
}): { points: Vec3[]; jds: number[]; groundJd: number } | null {
	const { outward, body, rParkKm, normal, periapsis, periJd, siteAt, bodyAt, center } = leg;
	const { includePeriapsis } = leg;
	if (!(body.mu > 0) || !(rParkKm > 0)) return null;
	const periodDays = (2 * Math.PI) / Math.sqrt(body.mu / rParkKm ** 3) / SEC_PER_DAY;

	// One pass of the geometry for a given site: angles and times, so the ground
	// date can be iterated before anything is sampled.
	const shape = (site: Vec3 | null) => {
		const s = site && norm(site) > 0 ? site : scale(periapsis, -body.radiusKm);
		const rSite = norm(s);
		if (!(rParkKm > rSite)) return null;
		const sHat = scale(s, 1 / rSite);
		const off = dot(sHat, normal);
		const inPlane = sub(sHat, scale(normal, off));
		const flat = norm(inPlane);
		// A site at the orbit's own pole has no in-plane shadow to steer by; land
		// opposite periapsis and let the bend carry the whole reach.
		const sPlane = flat > 1e-9 ? scale(inPlane, 1 / flat) : scale(periapsis, -1);
		const tilt = flat > 1e-9 ? off / flat : 0;
		// The half-ellipse spans π, so it leaves the orbit opposite the site.
		const gate = scale(sPlane, -1);
		const coast = outward
			? angleAbout(gate, periapsis, normal)
			: angleAbout(periapsis, gate, normal);
		const a = (rParkKm + rSite) / 2;
		const e = (rParkKm - rSite) / (rParkKm + rSite);
		const meanMotion = Math.sqrt(body.mu / a ** 3);
		return {
			sHat,
			rSite,
			sPlane,
			tilt,
			gate,
			coastDays: (coast / (2 * Math.PI)) * periodDays,
			coast,
			e,
			p: a * (1 - e * e),
			meanMotion,
			halfDays: Math.PI / meanMotion / SEC_PER_DAY
		};
	};

	let geo = shape(siteAt?.(periJd) ?? null);
	if (!geo) return null;
	let groundJd = periJd + (outward ? -1 : 1) * (geo.coastDays + geo.halfDays);
	if (siteAt) {
		for (let i = 0; i < 3; i++) {
			const next = shape(siteAt(groundJd));
			if (!next) return null;
			geo = next;
			groundJd = periJd + (outward ? -1 : 1) * (geo.coastDays + geo.halfDays);
		}
		// One last read at the settled date, holding the date itself: the ground
		// sample has to be the site exactly as read at the `groundJd` reported.
		const settled = shape(siteAt(groundJd));
		if (!settled) return null;
		geo = settled;
	}
	const { sHat, rSite, sPlane, tilt, gate, coastDays, coast, e, p, meanMotion } = geo;

	// Kepler on the half-ellipse: seconds from its periapsis — the ground — to
	// true anomaly `nu` in [0, π].
	const climbSeconds = (nu: number): number => {
		const E =
			2 * Math.atan2(Math.sqrt(1 - e) * Math.sin(nu / 2), Math.sqrt(1 + e) * Math.cos(nu / 2));
		return (E - e * Math.sin(E)) / meanMotion;
	};

	const points: Vec3[] = [];
	const jds: number[] = [];
	const put = (point: Vec3, jd: number) => {
		// A coast of no angle puts its samples on one date; anything reading the
		// line needs the dates increasing, so those fold into their neighbour.
		if (jds.length > 0 && jd <= jds[jds.length - 1] + 1e-9) return;
		// The same carried motion as the passage and the ring: without it the leg
		// would hang frozen at the encounter while the body sails on.
		const moved = bodyAt?.(jd);
		points.push(moved ? add(point, sub(moved, center)) : point);
		jds.push(jd);
	};
	// The ellipse point `phi` of the way from ground to gate; the ground sample
	// is the site itself, exactly as read.
	const ellipsePoint = (phi: number, inPlaneDir: Vec3): Vec3 => {
		if (phi === 0) return scale(sHat, rSite);
		const radius = p / (1 + e * Math.cos(phi));
		const reach = seamBlend(1 - phi / Math.PI) * tilt;
		return scale(normalize(add(inPlaneDir, scale(normal, reach))), radius);
	};

	const coastSamples = Math.max(2, Math.ceil((coast / (2 * Math.PI)) * RING_SAMPLES));
	if (outward) {
		// Ground first: climb `phi` from 0 at the site towards π at the gate — the
		// gate itself opens the coast — then round to the injection burn.
		for (let i = 0; i < DESCENT_SAMPLES; i++) {
			const phi = (Math.PI * i) / DESCENT_SAMPLES;
			put(
				ellipsePoint(phi, rotateAbout(sPlane, normal, phi)),
				groundJd + climbSeconds(phi) / SEC_PER_DAY
			);
		}
		const top = includePeriapsis ? coastSamples : coastSamples - 1;
		for (let i = 0; i <= top; i++) {
			const theta = (coast * i) / coastSamples;
			// Anchored on periapsis, so the top sample meets the passage on its date.
			put(
				scale(rotateAbout(gate, normal, theta), rParkKm),
				periJd - coastDays + (theta / (2 * Math.PI)) * periodDays
			);
		}
	} else {
		// Periapsis first: coast forward to the gate, then fall — `phi` runs π at
		// the gate down to 0 at the site.
		for (let i = includePeriapsis ? 0 : 1; i <= coastSamples; i++) {
			const theta = (coast * i) / coastSamples;
			put(
				scale(rotateAbout(periapsis, normal, theta), rParkKm),
				periJd + (theta / (2 * Math.PI)) * periodDays
			);
		}
		for (let i = 1; i <= DESCENT_SAMPLES; i++) {
			const phi = Math.PI - (Math.PI * i) / DESCENT_SAMPLES;
			// Anchored on the ground, so the last sample is the site on its date.
			put(
				ellipsePoint(phi, rotateAbout(gate, normal, Math.PI - phi)),
				groundJd - climbSeconds(phi) / SEC_PER_DAY
			);
		}
	}
	return { points, jds, groundJd };
}

/**
 * The orbit at an end of a trip, as the frame it is drawn in has it. A parking
 * orbit closes only in the frame of the body it goes round; drawn from
 * anywhere else it's a trochoid — Mars covers five million km in the two days
 * a capture orbit takes, smearing one revolution into a shallow scallop.
 *
 * Closed when the frame is the body's own, or when there's no way to ask where
 * the body was: `bodyAt` comes off the passage, and an end without one isn't
 * drawn at body scale anyway.
 */
function orbitRing(ring: {
	origin: Vec3;
	orbit: EndOrbit;
	normal: Vec3;
	periapsis: Vec3;
	mu: number;
	periJd: number;
	bodyAt?: (jd: number) => Vec3 | null;
	center: Vec3;
	outward: boolean;
}): { points: Vec3[]; jds?: number[] } {
	const { origin, orbit, normal, periapsis, mu, periJd, bodyAt, center, outward } = ring;
	const closed = closedOrbit(origin, orbit, normal, periapsis);
	const semiMajor = (orbit.rPeriKm + orbit.rApoKm) / 2;
	if (!(mu > 0) || !(semiMajor > 0)) return { points: closed };

	const e = (orbit.rApoKm - orbit.rPeriKm) / (orbit.rApoKm + orbit.rPeriKm);
	const periodDays = (2 * Math.PI * Math.sqrt(semiMajor ** 3 / mu)) / SEC_PER_DAY;

	const jds: number[] = [];
	const smeared: Vec3[] = [];
	let broken = false;
	for (let i = 0; i <= RING_SAMPLES; i++) {
		const nu = (Math.PI * 2 * i) / RING_SAMPLES;
		// Kepler's equation dates each ring point. A departure is in this orbit
		// *before* it leaves, so its revolution runs up to periapsis, not away.
		const anomaly =
			2 * Math.atan2(Math.sqrt(1 - e) * Math.sin(nu / 2), Math.sqrt(1 + e) * Math.cos(nu / 2));
		const mean = anomaly - e * Math.sin(anomaly);
		const days = (periodDays * mean) / (Math.PI * 2) - (outward ? periodDays : 0);
		jds.push(periJd + days);
		if (broken || !bodyAt) continue;
		const moved = bodyAt(periJd + days);
		if (!moved) {
			broken = true;
			continue;
		}
		smeared.push(add(closed[i], sub(moved, center)));
	}
	return { points: bodyAt && !broken ? smeared : closed, jds };
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

/** One end's join between the orbit round a body and the crossing outside it. */
interface Passage {
	/** Measured from the body, in flight order — the caller puts them wherever
	 *  that body is in the frame it is drawing. */
	points: Vec3[];
	jds: number[];
	periapsis: Vec3;
	normal: Vec3;
	/** The crossing sample the passage takes over at. */
	cut: number;
	center: Vec3;
	periJd: number;
}

/**
 * The escape or capture an end of a trip is flown on, from the crossing down
 * to periapsis or back out. Conic is derived (eccentricity from excess speed
 * and periapsis, asymptote angle from eccentricity); plane is chosen as the
 * nearest to the crossing's own among those holding the asymptote.
 *
 * Dates are its own, not the route's: pricing treats an arrival as the
 * crossing reaching the body's centre, a place the craft never goes. Really it
 * leaves the crossing at the moving sphere of influence and reaches periapsis
 * a hyperbolic fall later, hours before the priced date — `periJd`/`center`
 * carry that correction. A departure keeps its priced date, since its
 * periapsis is the injection burn.
 *
 * **The frame decides what this curve is.** `interplanetary` carries the
 * body's own motion, returning the patched-conic worldline continuing on from
 * the crossing (drawn about the Sun); `planetary` drops it, returning the bare
 * hyperbola off a body held still — the only difference between the two, so a
 * frame change moves the picture, never the craft. The handover sits on a
 * crossing sample, not a radius, and the two solvers' mutual disagreement
 * there is worked off along the fall in both frames.
 *
 * Null where there's no passage to draw: no μ, zero excess speed, or a
 * crossing too short to give one up.
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
	frame: TrajectoryFrame;
	/** A direction the plane should hold besides the asymptote — a landing site.
	 *  The plane is the passage's one free choice, and an end that is aimed
	 *  somewhere spends it there rather than on the crossing's own plane. */
	planeHint?: Vec3;
}): Passage | null {
	const { body, approach, rPeriKm, arcNormal, at, primaryMu, arc, endJd, frame, planeHint } = end;
	const { vInf, bodyAt } = approach;
	const speed = norm(vInf);
	if (!(speed > 0) || !(body.mu > 0) || !(rPeriKm > 0)) return null;

	const outward = at === 'departure';
	const asymptote = normalize(vInf);
	const off = planeHint
		? cross(asymptote, planeHint)
		: sub(arcNormal, scale(asymptote, dot(arcNormal, asymptote)));
	let normal = norm(off) > 0 ? normalize(off) : perpendicularTo(asymptote);
	// Of the two senses the hinted plane allows, keep the crossing's own.
	if (planeHint && dot(normal, arcNormal) < 0) normal = scale(normal, -1);

	const e = 1 + (rPeriKm * speed * speed) / body.mu;
	if (!(e > 1)) return null;
	const p = rPeriKm * (1 + e);
	// True anomaly of the asymptote: departs that far after periapsis, arrives
	// that far before.
	const nuInf = Math.acos(-1 / e);
	const periapsis = outward
		? rotateAbout(asymptote, normal, -nuInf)
		: rotateAbout(scale(asymptote, -1), normal, nuInf);
	const inPlane = normalize(cross(normal, periapsis));

	const outer = passageRadiusKm(body, primaryMu, rPeriKm);
	const nuOuter = Math.acos(Math.max(-1, Math.min(1, (p / outer - 1) / e)));
	if (!(nuOuter > 0)) return null;

	// Where the crossing really crosses the sphere, chased against the moving
	// body; the hyperbola's own clock stands in if the chase fails.
	const meanMotion = Math.sqrt(body.mu / Math.abs(p / (1 - e * e)) ** 3);
	const fallDays = hyperbolicSeconds(e, nuOuter, meanMotion) / SEC_PER_DAY;
	const crossJd =
		soiCrossingJd(approach, outer, outward) ?? endJd + (outward ? fallDays : -fallDays);
	const periJd = outward ? endJd : crossJd + fallDays;
	const center = bodyAt(periJd);
	if (!center) return null;

	// Where the crossing gives way: its last sample still outside the sphere.
	const cut = outward ? firstAfter(arc.jds, crossJd) : lastBefore(arc.jds, crossJd);
	// One sample either side at least, or there is no line left to draw.
	if (cut < 1 || cut > arc.points.length - 2) return null;

	// Sampled in time and squared so samples crowd at periapsis where the line
	// bends; even steps in true anomaly would put a million km between the
	// first two, out where the body's own motion dominates.
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
	// What the patched conic misses the crossing by at the join — two models
	// agreeing only to solver tolerance. Worked off along the way down so the
	// join is seamless and periapsis stays where the burn was priced.
	const miss = sub(sub(arc.points[cut], center), add(sample(joinDays), joinCarried));
	// A borrowed end is drawn about its live body, so it takes the planet-frame
	// shape rather than the ancestor's carried motion.
	const solar = frame === 'interplanetary' && body.borrowedElements !== true;

	const points: Vec3[] = [];
	const jds: number[] = [];
	for (let i = 0; i < PASSAGE_SAMPLES; i++) {
		const along = i / (PASSAGE_SAMPLES - 1);
		const fraction = outward ? along : 1 - along;
		const days = joinDays * fraction * fraction;
		const point = sample(days);
		jds.push(periJd + days);
		const seam = seamBlend((norm(point) - rPeriKm) / (outer - rPeriKm));
		const corrected = add(point, scale(miss, seam));
		// Planet-frame leaves out only the body's motion; the correction stays, or
		// the craft would move on a frame change.
		if (!solar) {
			points.push(corrected);
			continue;
		}
		const moved = carried(days);
		if (!moved) return null;
		points.push(add(corrected, moved));
	}
	return { points, jds, periapsis, normal, cut, center, periJd };
}

/** How much of the two models' disagreement a passage point still carries —
 *  all at the handover, none by periapsis — flat at both ends so the line
 *  meets the orbit and crossing along a tangent, not an angle. */
function seamBlend(x: number): number {
	const t = Math.max(0, Math.min(1, x));
	return t * t * (3 - 2 * t);
}

/** RK4 steps walked between one drawn point of a climb and the next. The drive
 *  is constant and the field smooth, so a handful holds it to metres. */
const ESCAPE_STEPS = 8;

/**
 * The climb out of a well under thrust — how a held drive leaves, the drive
 * being on from the parking orbit onwards. There is no asymptote to fall
 * along and no conic to derive, so it is flown: away from periapsis at the
 * escape speed the well was priced at (v∞ = 0), with the drive pointing where
 * the crossing says it points, until the date the crossing leaves the sphere
 * of influence.
 *
 * The burn is placed where the orbit already runs along the drive, which is
 * the one point on it an injection costs what it was priced at — and leaves
 * the ring and the climb sharing a tangent.
 *
 * Same frames and the same seam as {@link hyperbolicPassage}: the crossing
 * reckons the ship free of the body from the first moment, this one holds it
 * back, and the whole of their disagreement is worked off between the join and
 * periapsis.
 */
function poweredEscape(end: {
	body: TravelBody;
	approach: EndApproach;
	drive: { dir: Vec3; accelKmS2: number };
	rPeriKm: number;
	arcNormal: Vec3;
	primaryMu: number;
	arc: PathArc;
	endJd: number;
	frame: TrajectoryFrame;
	planeHint?: Vec3;
}): Passage | null {
	const { body, approach, drive, rPeriKm, arcNormal, primaryMu, arc, endJd, frame } = end;
	if (!(body.mu > 0) || !(rPeriKm > 0) || !(norm(drive.dir) > 0) || !(drive.accelKmS2 > 0)) {
		return null;
	}
	const along = normalize(drive.dir);
	const off = end.planeHint
		? cross(along, end.planeHint)
		: sub(arcNormal, scale(along, dot(arcNormal, along)));
	let normal = norm(off) > 0 ? normalize(off) : perpendicularTo(along);
	if (end.planeHint && dot(normal, arcNormal) < 0) normal = scale(normal, -1);
	// A quarter turn back from the drive, so the orbit's own motion there is the
	// way the ship is going.
	const periapsis = normalize(cross(along, normal));

	const outer = passageRadiusKm(body, primaryMu, rPeriKm);
	// The speed the walk steps by: how fast the drive alone crosses the sphere,
	// since the excess speed every other end is scaled from is zero here.
	const crossJd = soiCrossingJd(approach, outer, true, Math.sqrt((outer * drive.accelKmS2) / 2));
	if (crossJd === null) return null;
	const joinDays = crossJd - endJd;
	if (!(joinDays > 0)) return null;
	const center = approach.bodyAt(endJd);
	if (!center) return null;

	// Where the crossing gives way: its first sample past the sphere.
	const cut = firstAfter(arc.jds, crossJd);
	if (cut < 1 || cut > arc.points.length - 2) return null;

	// Sampled squared in time, so the steps crowd at periapsis where the line
	// bends — the integration follows them, which is what keeps the first
	// revolution's worth of curve honest under a drive too weak to dominate it.
	const spans: number[] = [];
	for (let i = 0; i < PASSAGE_SAMPLES; i++) {
		const fraction = i / (PASSAGE_SAMPLES - 1);
		spans.push(joinDays * fraction * fraction);
	}
	const flown = samplePoweredFlight(
		{ r: scale(periapsis, rPeriKm), v: scale(along, Math.sqrt((2 * body.mu) / rPeriKm)) },
		scale(along, drive.accelKmS2),
		body.mu,
		spans.map((days) => days * SEC_PER_DAY),
		ESCAPE_STEPS
	);
	if (flown.length < PASSAGE_SAMPLES) return null;
	const carried = (days: number): Vec3 | null => {
		const moved = approach.bodyAt(endJd + days);
		return moved ? sub(moved, center) : null;
	};
	const joinCarried = carried(joinDays);
	if (!joinCarried) return null;
	const miss = sub(sub(arc.points[cut], center), add(flown[flown.length - 1], joinCarried));
	const solar = frame === 'interplanetary' && body.borrowedElements !== true;

	const points: Vec3[] = [];
	const jds: number[] = [];
	for (let i = 0; i < PASSAGE_SAMPLES; i++) {
		const days = spans[i];
		const point = flown[i];
		jds.push(endJd + days);
		const seam = seamBlend((norm(point) - rPeriKm) / (outer - rPeriKm));
		const corrected = add(point, scale(miss, seam));
		if (!solar) {
			points.push(corrected);
			continue;
		}
		const moved = carried(days);
		if (!moved) return null;
		points.push(add(corrected, moved));
	}
	return { points, jds, periapsis, normal, cut, center, periJd: endJd };
}

/** Points along each branch of a swing-by pass. The two share periapsis, so the
 *  drawn passage is one sample short of twice this. */
const FLYBY_BRANCH_SAMPLES = 80;

/**
 * The pass a swing-by is actually flown on, replacing the corner the two arcs
 * make at the body's centre. The same solve pricing ran fixes everything: the
 * periapsis radius comes from `solveFlyby` on the same excess velocities, and
 * each side of the pass is the hyperbola that speed and periapsis make — two
 * conics, since a powered pass changes speed at the low point. The plane is
 * the one both excess velocities lie in (the plane the turn happens in); the
 * shared periapsis sits where the incoming asymptote demands.
 *
 * Like an end's passage, it's the patched-conic worldline: body displacement
 * carried along it, each handover chased to the moving sphere of influence,
 * and the models' mutual miss worked off down to periapsis so the passage
 * meets both arcs at a shared sample.
 *
 * Null with no pass to draw: solve failure, periapsis at the sphere's edge
 * (really a burn wearing the name), a turn too small to pick a plane, or a
 * crossing too short to give up its end. The corner is the honest fallback.
 */
function assistPassage(pass: {
	via: TravelBody;
	/** The via body's state at the priced pass date. */
	mid: { r: Vec3; v: Vec3 };
	/** The craft's heliocentric velocity arriving at the body, off the first arc. */
	vIn: Vec3;
	/** And leaving it, off the second. */
	vOut: Vec3;
	first: PathArc;
	second: PathArc;
	flybyJd: number;
	centralMu: number;
}): {
	/** In the transfer frame, in flight order. */
	points: Vec3[];
	jds: number[];
	/** The first arc keeps `[0, cutIn]`, the second `[cutOut, end)`. */
	cutIn: number;
	cutOut: number;
	/** The drawn low point, transfer frame. */
	peri: Vec3;
	periJd: number;
} | null {
	const { via, mid, vIn, vOut, first, second, flybyJd, centralMu } = pass;
	const vInfIn = sub(vIn, mid.v);
	const vInfOut = sub(vOut, mid.v);
	const soi = sphereOfInfluenceKm(via, centralMu, Math.abs(via.elements.a) * AU_KM);
	if (!Number.isFinite(soi) || !(soi > 0)) return null;

	const solved = solveFlyby(via, vInfIn, vInfOut, soi);
	if (!solved || !(solved.periapsisKm < soi * 0.99)) return null;
	const rPeri = solved.periapsisKm;

	const crossed = cross(vInfIn, vInfOut);
	if (!(norm(crossed) > 0)) return null;
	const normal = normalize(crossed);

	const speedIn = norm(vInfIn);
	const speedOut = norm(vInfOut);
	const eIn = 1 + (rPeri * speedIn * speedIn) / via.mu;
	const eOut = 1 + (rPeri * speedOut * speedOut) / via.mu;
	if (!(eIn > 1) || !(eOut > 1)) return null;

	// The craft comes in along `vInfIn`, so periapsis is the asymptote's true
	// anomaly on from the opposite direction; the outgoing branch lines up with
	// the other asymptote by the same geometry — exactly what periapsis was
	// solved for.
	const nuInfIn = Math.acos(-1 / eIn);
	const periapsis = rotateAbout(normalize(vInfIn), normal, nuInfIn - Math.PI);
	const inPlane = normalize(cross(normal, periapsis));

	const branch = (e: number) => {
		const p = rPeri * (1 + e);
		const meanMotion = Math.sqrt(via.mu / Math.abs(p / (1 - e * e)) ** 3);
		const nuSoi = Math.acos(Math.max(-1, Math.min(1, (p / soi - 1) / e)));
		const fallDays = hyperbolicSeconds(e, nuSoi, meanMotion) / SEC_PER_DAY;
		const sample = (days: number): Vec3 => {
			const nu = hyperbolicTrueAnomaly(e, days * SEC_PER_DAY * meanMotion);
			const radius = p / (1 + e * Math.cos(nu));
			return scale(add(scale(periapsis, Math.cos(nu)), scale(inPlane, Math.sin(nu))), radius);
		};
		return { fallDays, sample };
	};
	const inward = branch(eIn);
	const outward = branch(eOut);
	if (!(inward.fallDays > 0) || !(outward.fallDays > 0)) return null;

	const viaAt = (jd: number) => elementsToState(via.elements, jd, centralMu)?.r ?? null;
	const chase = (v: Vec3, vInf: Vec3, leaving: boolean) =>
		soiCrossingJd(
			{
				vInf,
				bodyAt: viaAt,
				craftAt: conicCraftAt({ r: mid.r, v, jd: flybyJd }, centralMu),
				jd: flybyJd
			},
			soi,
			leaving
		);
	const entryJd = chase(vIn, vInfIn, false) ?? flybyJd - inward.fallDays;
	const exitJd = chase(vOut, vInfOut, true) ?? flybyJd + outward.fallDays;
	// One clock for the whole pass, anchored on the entry: periapsis is a fall
	// after it, and the way out is read off that same low point.
	const periJd = entryJd + inward.fallDays;

	const cutIn = lastBefore(first.jds, entryJd);
	const cutOut = firstAfter(second.jds, exitJd);
	// At least one sample must stay either side, or there is no arc left to join.
	if (cutIn < 1 || cutOut < 0 || cutOut > second.points.length - 2) return null;

	const center = viaAt(periJd);
	if (!center) return null;
	const carried = (days: number): Vec3 | null => {
		const moved = viaAt(periJd + days);
		return moved ? sub(moved, center) : null;
	};

	const joinIn = first.jds[cutIn] - periJd;
	const joinOut = second.jds[cutOut] - periJd;
	if (!(joinIn < 0) || !(joinOut > 0)) return null;
	const carriedIn = carried(joinIn);
	const carriedOut = carried(joinOut);
	if (!carriedIn || !carriedOut) return null;
	// What each conic misses its own arc by at the handover — see the end
	// passage's seam for why it is worked off along the way down.
	const missIn = sub(sub(first.points[cutIn], center), add(inward.sample(joinIn), carriedIn));
	const missOut = sub(sub(second.points[cutOut], center), add(outward.sample(joinOut), carriedOut));

	const points: Vec3[] = [];
	const jds: number[] = [];
	const push = (days: number, half: typeof inward, miss: Vec3): boolean => {
		const point = half.sample(days);
		const moved = carried(days);
		if (!moved) return false;
		const seam = seamBlend((norm(point) - rPeri) / (soi - rPeri));
		points.push(add(center, add(point, add(moved, scale(miss, seam)))));
		jds.push(periJd + days);
		return true;
	};
	// Squared along each branch so the samples crowd at periapsis, where the line
	// bends hardest.
	for (let i = 0; i < FLYBY_BRANCH_SAMPLES; i++) {
		const fraction = 1 - i / (FLYBY_BRANCH_SAMPLES - 1);
		if (!push(joinIn * fraction * fraction, inward, missIn)) return null;
	}
	for (let i = 1; i < FLYBY_BRANCH_SAMPLES; i++) {
		const fraction = i / (FLYBY_BRANCH_SAMPLES - 1);
		if (!push(joinOut * fraction * fraction, outward, missOut)) return null;
	}
	return { points, jds, cutIn, cutOut, peri: add(center, scale(periapsis, rPeri)), periJd };
}

/**
 * When the crossing crosses the body's sphere of influence, as a date. Solved
 * against the moving body rather than read off the hyperbola's clock, since
 * the crossing was solved to the body's centre and the body doesn't wait
 * there. Walked out from the centre-meeting date (certainly inside the
 * sphere), then bisected.
 *
 * Null when the walk never leaves the sphere or either curve can't be
 * evaluated; the caller falls back to the hyperbola's own clock.
 */
/** Doublings the walk out to the sphere takes, and the share of its first guess
 *  it starts from — the same number, so the walk still reaches far past that
 *  guess when the sphere is crossed slower than the excess speed suggests. */
const WALK_STEPS = 16;

function soiCrossingJd(
	approach: EndApproach,
	soiKm: number,
	outward: boolean,
	speedKms?: number
): number | null {
	const { bodyAt, craftAt, jd: fromJd } = approach;
	const speed = speedKms ?? norm(approach.vInf);
	if (!(speed > 0) || !(soiKm > 0)) return null;

	const separation = (jd: number): number | null => {
		const r = craftAt(jd);
		const body = bodyAt(jd);
		return r && body ? norm(sub(r, body)) - soiKm : null;
	};

	const direction = outward ? 1 : -1;
	// Doubled out from well inside the excess speed's own estimate of the
	// crossing: under thrust the craft covers the sphere far faster than that,
	// and a first probe past the end of what can be evaluated finds nothing.
	let step = soiKm / speed / SEC_PER_DAY / WALK_STEPS;
	let inside = fromJd;
	let outside: number | null = null;
	for (let i = 0; i < WALK_STEPS && outside === null; i++) {
		const jd = fromJd + direction * step;
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
 * A drive held all the way, re-flown. The crossing is integrated under the
 * primary's pull, so drawing it means flying it again; the route carries the
 * one thing that can't be re-derived — where the drive pointed — so this is a
 * single forward pass, not a second shooting solve, and draws exactly the arc
 * priced. Falls back to the chord for a route with no direction on it (built
 * before this module answered in curves).
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

/** The stretch of trip spent at `body` between two dates, as the body's own
 *  path. Null when there's no stretch to draw — a spiral taking an afternoon
 *  is a point, and a flyby has no arrival spiral at all. */
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
 * The crossing of a spiral route: the orbit opening out from one body's to the
 * other's over however many revolutions that takes. Radii and angle come from
 * the same priced transfer, rebuilt not carried. Imposed on top: the model
 * matches circular orbits, but the bodies are eccentric and inclined, so the
 * arc is stretched onto where they actually are — a few percent correction, or
 * the picture would miss the destination planet.
 *
 * The two end spirals are drawn as the body's own path over the months they
 * take. They're a dot at this scale, inside a sphere of influence, but a third
 * of the trip — leaving them out stopped the craft dead at the encounter while
 * the clock ran on for another year.
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

	// Revolutions come from the model; where the target sits on the last one
	// comes from the target. They agree to within a fraction of a turn (that's
	// what the departure date was solved for), so the drawn sweep rounds the
	// modelled one onto the arrival.
	const closing = angleAbout(u0, u1, normal);
	const turns = Math.max(0, Math.round((transfer.sweepRad - closing) / (Math.PI * 2)));
	const sweep = closing + turns * Math.PI * 2;
	if (!(sweep > 0)) return null;

	// The two orbits aren't coplanar, so the arc turns out of the departure's
	// plane as it goes.
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

	// Climbing out of one well and dropping into the other: the craft rounds a
	// body that itself rounds the Sun, so a heliocentric picture can only show
	// the body's own path over those months.
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
			// Stretches share the state they meet at.
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
				dvKms: dvOf(route, ['capture', 'raise', 'descent'])
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
	// crossing is one arc; a coast between burns is the other shape change,
	// and both are read back off the legs.
	const flips = route.legs.some((leg) => leg.kind === 'brake');
	const boostDays = route.legs.find((leg) => leg.kind === 'boost')?.days ?? route.tofDays;
	const coastDays = route.legs.find((leg) => leg.kind === 'cruise')?.days ?? 0;
	const half = Math.max(2, Math.round(samples / 2));

	/**
	 * A stretch of the line, sampled evenly along it — *not* evenly in time,
	 * since a drive covers ground as ½at² and crawls at the start of a burn.
	 * `timeFraction` turns a sample's place on the line into the fraction of the
	 * stretch's time it's reached at, which the dates are built from.
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

	// Accelerating from rest, distance goes as time squared, so time is the
	// square root of distance. Braking runs the same backwards; a coast is even
	// in both.
	const accelerating = (along: number) => Math.sqrt(along);
	const braking = (along: number) => 1 - Math.sqrt(Math.max(0, 1 - along));
	const even = (along: number) => along;

	// Ground each stretch covers (½at² under thrust, vt coasting), in whatever
	// units `boostDays` is in — only the shares matter, so acceleration cancels
	// and is never needed here.
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
		// Pinned to the far end rather than accumulated, so rounding can't leave
		// the arc short of the body it arrives at.
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
				dvKms: dvOf(route, ['capture', 'raise', 'descent'])
			}
		],
		meeting: { bodyId: targetId, jd: route.arriveJd, r: end }
	};
}

/**
 * A trip between a body and one of its own satellites. Pricing fixes the
 * arc's energy and two radii but not its plane — it never needed one. Drawing
 * does: the satellite's own plane is the one a real mission flies, leaving the
 * parking orbit at periapsis and climbing to meet the satellite where it is.
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
		dvKms: dvOf(route, ['capture', 'raise', 'descent'])
	};

	if (route.constantThrust != null) {
		// A held drive ignores the transfer ellipse: it crosses straight between
		// the primary's parking orbit and the satellite.
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

	// The plane is the satellite's, and the arc's far end is where it is.
	const normal = normalize(cross(state.r, state.v));
	if (!(norm(normal) > 0)) return null;
	const sampled = radialArcSamples(
		arc,
		rNear,
		rFar,
		normalize(state.r),
		normal,
		route,
		outbound,
		samples
	);
	if (!sampled) return null;

	return {
		centerId,
		arcs: [{ ...sampled, kind: 'cruise', startJd: route.departJd, endJd: route.arriveJd }],
		stops: [departureStop, arrivalStop],
		meeting
	};
}

/**
 * Sample a radial arc from its periapsis out to `rFarKm`, and date every point.
 *
 * The conic is placed by its far end: periapsis sits behind `farDir` by the
 * true anomaly the arc reaches it at, in the plane `normal` describes. Read
 * outbound the points run from periapsis outwards, and inbound they are the
 * same arc reversed — the way home is the way out flown backwards.
 */
function radialArcSamples(
	arc: RadialArc,
	rNearKm: number,
	rFarKm: number,
	farDir: Vec3,
	normal: Vec3,
	route: Route,
	outbound: boolean,
	samples: number = DEFAULT_SAMPLES
): { points: Vec3[]; jds: number[] } | null {
	const a = 1 / arc.inverseAKm;
	const e = 1 - rNearKm * arc.inverseAKm;
	const p = a * (1 - e * e);
	if (!isFinite(p) || !(p > 0)) return null;

	// True anomaly where the arc reaches the far radius, from the conic equation.
	const cosNu = (p / rFarKm - 1) / (e || 1e-12);
	const nuFar = Math.acos(Math.max(-1, Math.min(1, cosNu)));
	if (!isFinite(nuFar)) return null;

	// Rotate `farDir` back by nuFar about the normal (Rodrigues, on unit vectors).
	const cosBack = Math.cos(-nuFar);
	const sinBack = Math.sin(-nuFar);
	const periapsis = normalize(
		add(
			add(scale(farDir, cosBack), scale(cross(normal, farDir), sinBack)),
			scale(normal, dot(normal, farDir) * (1 - cosBack))
		)
	);
	return sweepSamples(
		e,
		p,
		nuFar,
		periapsis,
		normalize(cross(normal, periapsis)),
		route,
		outbound,
		samples
	);
}

/**
 * The arc of a trip between two orbits about one body.
 *
 * Drawn in the body's own equator: the pricing charges a named plane's turn,
 * but no node is tracked, so the one plane the drawing can honestly claim is
 * the one the body itself turns in. Where the two orbits already meet there is
 * no arc to draw at all, and what is drawn is the half turn the craft coasts
 * to reach the burn.
 */
function orbitChangePath(
	body: TravelBody,
	route: Route,
	centerId: string,
	samples: number
): PathGeometry | null {
	const ends = orbitChangeEnds(body, {
		departureMode: route.departureMode,
		arrivalMode: route.arrivalMode,
		departureOrbit: route.departureOrbit,
		targetOrbit: route.targetOrbit
	});
	if (!ends) return null;

	// The body's equator where its pole is published, the ecliptic where it is
	// not: an unstated pole is not a claim that the orbit lies anywhere else.
	const normal = normalize(body.poleEcliptic ?? ([0, 0, 1] as Vec3));
	if (!(norm(normal) > 0)) return null;
	// Nothing picks out a direction in the plane, so periapsis goes wherever the
	// axes put it: any longitude draws the same trip.
	const periapsis = normalize(cross(normal, Math.abs(normal[0]) < 0.9 ? [1, 0, 0] : [0, 1, 0]));
	const inPlane = normalize(cross(normal, periapsis));

	const rNear = Math.min(ends.rFromKm, ends.rToKm);
	const rFar = Math.max(ends.rFromKm, ends.rToKm);
	const sampled = ends.singleBurn
		? sweepSamples(
				eccentricityOf(ends.from),
				semiLatusRectumOf(ends.from),
				Math.PI,
				periapsis,
				inPlane,
				route,
				true,
				samples
			)
		: sweepFromArc(body, rNear, rFar, periapsis, inPlane, route, ends.climb, samples);
	if (!sampled) return null;

	const { points, jds } = sampled;
	const stops: PathStop[] = [
		{
			kind: 'departure',
			jd: route.departJd,
			r: points[0],
			bodyId: body.id,
			dvKms: dvOf(route, ['ascent', 'injection'])
		},
		{
			kind: 'arrival',
			jd: route.arriveJd,
			r: points[points.length - 1],
			bodyId: body.id,
			dvKms: dvOf(route, ['capture', 'raise', 'descent'])
		}
	];
	return {
		centerId,
		arcs: [{ kind: 'cruise', points, jds, startJd: route.departJd, endJd: route.arriveJd }],
		stops,
		// The destination is the body the whole trip is measured from, so it never
		// moves under the arc: the meeting is at its centre.
		meeting: { bodyId: body.id, jd: route.arriveJd, r: [0, 0, 0] as Vec3 }
	};
}

/** Eccentricity and semi-latus rectum of a named orbit — the two numbers a
 *  sweep needs, from the two radii an end is described by. */
function eccentricityOf(orbit: EndOrbit): number {
	const sum = orbit.rApoKm + orbit.rPeriKm;
	return sum > 0 ? (orbit.rApoKm - orbit.rPeriKm) / sum : 0;
}

function semiLatusRectumOf(orbit: EndOrbit): number {
	const sum = orbit.rApoKm + orbit.rPeriKm;
	return sum > 0 ? (2 * orbit.rApoKm * orbit.rPeriKm) / sum : 0;
}

/** The transfer ellipse between two radii about one body, sampled in a plane
 *  that nothing else fixes. Climbing it runs outwards; coming down it is the
 *  same arc read backwards. */
function sweepFromArc(
	body: TravelBody,
	rNearKm: number,
	rFarKm: number,
	periapsis: Vec3,
	inPlane: Vec3,
	route: Route,
	climb: boolean,
	samples: number
): { points: Vec3[]; jds: number[] } | null {
	const arc = solveRadialArc(body.mu, rNearKm, rFarKm, route.tofDays);
	if (!arc) return null;
	const a = 1 / arc.inverseAKm;
	const e = 1 - rNearKm * arc.inverseAKm;
	const p = a * (1 - e * e);
	if (!isFinite(p) || !(p > 0)) return null;
	const cosNu = (p / rFarKm - 1) / (e || 1e-12);
	const nuFar = Math.acos(Math.max(-1, Math.min(1, cosNu)));
	if (!isFinite(nuFar)) return null;
	return sweepSamples(e, p, nuFar, periapsis, inPlane, route, climb, samples);
}

/**
 * Points and dates along a conic, from its periapsis through `nuEnd` of true
 * anomaly. `outbound` reads it away from the body; false reads the same sweep
 * backwards, which is the way home.
 */
function sweepSamples(
	e: number,
	p: number,
	nuEnd: number,
	periapsis: Vec3,
	inPlane: Vec3,
	route: Route,
	outbound: boolean,
	samples: number
): { points: Vec3[]; jds: number[] } | null {
	const points: Vec3[] = [];
	// Time from periapsis to each sample, recovering dates from a sweep taken
	// evenly in angle rather than time (Kepler's equation; units cancel below).
	const sincePeriapsis: number[] = [];
	for (let i = 0; i < samples; i++) {
		const nu = (nuEnd * i) / (samples - 1);
		const radius = p / (1 + e * Math.cos(nu));
		if (!isFinite(radius) || radius <= 0) return null;
		points.push(scale(add(scale(periapsis, Math.cos(nu)), scale(inPlane, Math.sin(nu))), radius));
		const anomaly =
			2 * Math.atan2(Math.sqrt(1 - e) * Math.sin(nu / 2), Math.sqrt(1 + e) * Math.cos(nu / 2));
		sincePeriapsis.push(anomaly - e * Math.sin(anomaly));
	}

	// Scaled to the flight time the route was solved for rather than to a period
	// derived here, so the ends land exactly on the two dates it names.
	const sweep = sincePeriapsis[samples - 1];
	const elapsed = sincePeriapsis.map((mean) =>
		sweep > 0 && isFinite(sweep) ? (route.tofDays * mean) / sweep : 0
	);
	const jds = outbound
		? elapsed.map((days) => route.departJd + days)
		: elapsed.map((days) => route.arriveJd - days).reverse();
	if (!outbound) points.reverse();
	return { points, jds };
}
