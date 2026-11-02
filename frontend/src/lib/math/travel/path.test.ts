import { describe, it, expect } from 'vitest';
import {
	buildTrajectoryPath,
	pathViewpoint,
	type EndOrbitPath,
	type TrajectoryFrame,
	type TrajectoryPath
} from './path';
import { craftPositionAt, crossingWindow } from './path-sample';
import { buildRoute, type Route } from './route';
import { buildAssistRoute } from './assist';
import { buildConstantThrustRoute } from './brachistochrone';
import {
	buildInterstellarCruiseRoute,
	buildInterstellarTorchRoute,
	coastShape,
	conicPlaceKm,
	crossingElapsed,
	endPlaceKm,
	heldLine,
	orbitStateAt,
	rapidityOfSpeed,
	type InterstellarCruiseOptions,
	type SystemEnd
} from './interstellar';
import { elementsToState } from './state';
import { hohmannTransferDays, nextTransferWindows } from './windows';
import { G0_M_S2, GM_SUN_KM3_S2, SEC_PER_DAY } from './constants';
import * as travelConstants from './constants';
import { AU_KM, LIGHT_YEAR_KM } from '$lib/math/units';
import { sphereOfInfluenceKm } from './body';
import { aeroPassRadiusKm, parkingOrbit, parkingRadiusKm, type EndOrbit } from './maneuvers';
import { add, cross, dot, norm, normalize, scale, sub, type Vec3 } from './vec3';
import {
	EARTH,
	J2000,
	JUPITER,
	MARS,
	MOON,
	PARABOLIC_COMET,
	PARABOLIC_COMET_FAR,
	VENUS
} from './test-fixtures';

const SUN = 'naif-10';
const MARS_WINDOW = nextTransferWindows(EARTH, MARS, J2000, 1)[0];
const MARS_TOF = hohmannTransferDays(EARTH, MARS)!;
/** Earth → Venus → Jupiter, on dates the kernel does find a flyable pass for. */
const ASSIST_ROUTE = buildAssistRoute(EARTH, VENUS, JUPITER, J2000, 150, 400)!;

/** How far apart two points are as a fraction of the second one's distance. */
function relative(a: Vec3, b: Vec3): number {
	return norm(sub(a, b)) / norm(b);
}

/** Where `body`'s own pull takes over from `primaryMu`'s, km — the radius the
 *  crossing is handed over to a passage at. */
function soiOf(body: typeof EARTH, primaryMu: number): number {
	return sphereOfInfluenceKm(body, primaryMu, body.elements.a * AU_KM);
}

describe('buildTrajectoryPath', () => {
	it('draws an arc whose ends sit on the two bodies', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path).not.toBeNull();

		const earthAt = elementsToState(EARTH.elements, route.departJd)!;
		const marsAt = elementsToState(MARS.elements, route.arriveJd)!;
		const points = path.arcs[0].points;
		expect(relative(points[0], earthAt.r)).toBeLessThan(1e-9);
		expect(relative(points[points.length - 1], marsAt.r)).toBeLessThan(1e-9);
	});

	it('stays between the two orbits the whole way across', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		// A Hohmann-like transfer never dips inside Earth's perihelion nor climbs
		// past Mars' aphelion; a propagator running off would show up here first.
		for (const point of path.arcs[0].points) {
			const au = norm(point) / 1.495978707e8;
			expect(au).toBeGreaterThan(0.9);
			expect(au).toBeLessThan(1.7);
		}
	});

	it('marks the meeting at the destination rather than where it is today', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const marsNow = elementsToState(MARS.elements, route.departJd)!;

		// The date is the arrival's, corrected by the passage: the craft is at
		// periapsis hours before the crossing would have reached the centre.
		expect(path.meeting.jd).toBeLessThanOrEqual(route.arriveJd);
		expect(path.meeting.jd).toBeGreaterThan(route.arriveJd - 1);
		expect(path.meeting.bodyId).toBe(MARS.id);
		const marsThen = elementsToState(MARS.elements, path.meeting.jd)!;
		expect(relative(path.meeting.r, marsThen.r)).toBeLessThan(1e-9);
		// Mars covers most of a radian over a transfer, so the two are nowhere
		// near each other — which is the whole reason to draw the meeting.
		expect(relative(path.meeting.r, marsNow.r)).toBeGreaterThan(0.5);
	});

	it('carries the burns as stops priced off the route', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path.stops.map((s) => s.kind)).toEqual(['departure', 'arrival']);

		const ascent = route.legs.find((l) => l.kind === 'ascent')!.dvKms;
		const injection = route.legs.find((l) => l.kind === 'injection')!.dvKms;
		expect(path.stops[0].dvKms).toBeCloseTo(ascent + injection, 9);
		// Every leg is charged to one stop or the other, so the two add up.
		const total = path.stops.reduce((sum, s) => sum + s.dvKms, 0);
		expect(total).toBeCloseTo(route.totalDvKms, 9);
	});

	it('breaks a swing-by into two arcs joined by the pass round the body', () => {
		const route = ASSIST_ROUTE;
		const path = buildTrajectoryPath(EARTH, JUPITER, route, { centerId: SUN, vias: [VENUS] })!;
		expect(path.arcs).toHaveLength(3);
		expect(path.stops.map((s) => s.kind)).toEqual(['departure', 'assist', 'arrival']);

		const [first, pass, second] = path.arcs.map((arc) => arc.points);
		// One trajectory: each handover is a sample the two stretches share.
		expect(relative(first[first.length - 1], pass[0])).toBeLessThan(1e-9);
		expect(relative(pass[pass.length - 1], second[0])).toBeLessThan(1e-9);
	});

	it('flies the pass the swing-by was priced on, not a corner at the centre', () => {
		const route = ASSIST_ROUTE;
		const flyby = route.flybys![0];
		const path = buildTrajectoryPath(EARTH, JUPITER, route, { centerId: SUN, vias: [VENUS] })!;
		const pass = path.arcs[1];
		const soi = soiOf(VENUS, GM_SUN_KM3_S2);

		const venusAt = (jd: number) => elementsToState(VENUS.elements, jd)!.r;
		const radii = pass.points.map((point, i) => norm(sub(point, venusAt(pass.jds[i]))));
		let low = Infinity;
		let lowest = 0;
		for (const [i, radius] of radii.entries()) {
			if (radius < low) {
				low = radius;
				lowest = i;
			}
		}
		// The pass hands over out at the sphere of influence — each end reaches the
		// arc's own sampling, so "near" is a step of the crossing, not a few km —
		// and dives from there to the body.
		expect(radii[0]).toBeGreaterThan(soi / 2);
		expect(radii[radii.length - 1]).toBeGreaterThan(soi / 2);
		expect(low).toBeLessThan(soi / 50);
		// Its low point is the periapsis the route priced the pass at, and the
		// assist's own stop sits there rather than at the body's centre.
		expect(low).toBeCloseTo(flyby.altitudeKm + VENUS.radiusKm, -1);
		expect(relative(path.stops[1].r, pass.points[lowest])).toBeLessThan(1e-6);

		// And its clock runs forward through the priced date.
		for (let i = 1; i < pass.jds.length; i++) expect(pass.jds[i]).toBeGreaterThan(pass.jds[i - 1]);
		expect(pass.startJd).toBeLessThan(flyby.jd);
		expect(pass.endJd).toBeGreaterThan(flyby.jd);
	});

	it('refuses a swing-by whose via body it was not given', () => {
		expect(buildTrajectoryPath(EARTH, JUPITER, ASSIST_ROUTE, { centerId: SUN })).toBeNull();
	});

	it('draws the arc the drive actually flew, which is not the chord', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1)!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path.arcs.map((a) => a.kind)).toEqual(['boost', 'brake']);

		const start = path.arcs[0].points[0];
		const end = path.arcs[1].points[path.arcs[1].points.length - 1];
		const flip = path.arcs[0].points[path.arcs[0].points.length - 1];
		// The two stretches share the state they meet at.
		expect(relative(flip, path.arcs[1].points[0])).toBeLessThan(1e-9);
		// And the path bows off the chord, because the Sun bent it. A point on the
		// chord satisfies |p−start| + |end−p| = |end−start|; these do not.
		const chord = norm(sub(end, start));
		const bow = Math.max(
			...path.arcs.flatMap((arc) =>
				arc.points.map((p) => norm(sub(p, start)) + norm(sub(end, p)) - chord)
			)
		);
		expect(bow).toBeGreaterThan(chord * 1e-4);
	});

	it('draws the coast as its own stretch, curving under the Sun', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1, { coastFraction: 1 })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path.arcs.map((a) => a.kind)).toEqual(['boost', 'cruise', 'brake']);

		const [boost, cruise, brake] = path.arcs;
		expect(relative(boost.points[boost.points.length - 1], cruise.points[0])).toBeLessThan(1e-9);
		expect(relative(cruise.points[cruise.points.length - 1], brake.points[0])).toBeLessThan(1e-9);
		expect(cruise.jds[0]).toBeCloseTo(boost.endJd, 9);
		expect(brake.endJd).toBeCloseTo(route.arriveJd, 9);

		// The coast is a conic, not a chord: its own midpoint sits off the line
		// joining its ends, by kilometres you could see on the map.
		const from = cruise.points[0];
		const to = cruise.points[cruise.points.length - 1];
		const span = norm(sub(to, from));
		const mid = cruise.points[Math.floor(cruise.points.length / 2)];
		expect(norm(sub(mid, from)) + norm(sub(to, mid)) - span).toBeGreaterThan(span * 1e-4);
		// Sampled finely enough to draw that curve rather than imply it.
		expect(cruise.points.length).toBeGreaterThan(8);
	});

	it('keeps a flyby crossing on one arc, since nothing slows it down', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1, { arrivalMode: 'flyby' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path.arcs.map((a) => a.kind)).toEqual(['boost']);
	});

	it('draws the hyperbolic arc between two long-period comets', () => {
		// Both are hundreds of AU out and receding, so the arc joining them is a
		// hyperbola rather than the ellipse an ordinary transfer is. Nothing
		// upstream flags that, so the propagator has to be total over every conic
		// or the path simply stops partway and the map draws nothing.
		const route = buildRoute(PARABOLIC_COMET, PARABOLIC_COMET_FAR, J2000 + 9000, 240_000)!;
		expect(route).not.toBeNull();
		const path = buildTrajectoryPath(PARABOLIC_COMET, PARABOLIC_COMET_FAR, route, {
			centerId: SUN
		});
		expect(path).not.toBeNull();

		const points = path!.arcs[0].points;
		expect(points).toHaveLength(180);
		for (const point of points) expect(Number.isFinite(norm(point))).toBe(true);
		// Ends on the two bodies, the same contract every other arc keeps.
		const from = elementsToState(PARABOLIC_COMET.elements, route.departJd)!;
		const to = elementsToState(PARABOLIC_COMET_FAR.elements, route.arriveJd)!;
		expect(relative(points[0], from.r)).toBeLessThan(1e-9);
		expect(relative(points[points.length - 1], to.r)).toBeLessThan(1e-9);
	});

	it('climbs from a parking orbit to the moon it is going to meet', () => {
		const tof = 5;
		const route = buildRoute(EARTH, MOON, J2000, tof, { systemPrimary: 'departure' })!;
		const path = buildTrajectoryPath(EARTH, MOON, route, {
			centerId: EARTH.id,
			systemPrimary: 'departure'
		})!;
		expect(path).not.toBeNull();

		const points = path.arcs[0].points;
		const start = norm(points[0]);
		const end = norm(points[points.length - 1]);
		// Starts just above Earth and ends out at the Moon's distance.
		expect(start).toBeLessThan(10_000);
		expect(end).toBeGreaterThan(300_000);
		// It climbs the whole way rather than looping.
		for (let i = 1; i < points.length; i++) {
			expect(norm(points[i])).toBeGreaterThan(norm(points[i - 1]) - 1);
		}
	});

	it('reads the same arc backwards on the way home', () => {
		const tof = 5;
		const out = buildTrajectoryPath(
			EARTH,
			MOON,
			buildRoute(EARTH, MOON, J2000, tof, { systemPrimary: 'departure' })!,
			{ centerId: EARTH.id, systemPrimary: 'departure' }
		)!;
		const home = buildTrajectoryPath(
			MOON,
			EARTH,
			buildRoute(MOON, EARTH, J2000, tof, { systemPrimary: 'target' })!,
			{ centerId: EARTH.id, systemPrimary: 'target' }
		)!;
		const homePoints = home.arcs[0].points;
		expect(norm(homePoints[0])).toBeGreaterThan(300_000);
		expect(norm(homePoints[homePoints.length - 1])).toBeLessThan(10_000);
		expect(out.arcs[0].points).toHaveLength(homePoints.length);
	});
});

describe('a same-system arc from a priced orbit', () => {
	const TOF = 4;
	const HIGH: EndOrbit = { rPeriKm: 100_000, rApoKm: 100_000 };
	const ELLIPSE: EndOrbit = { rPeriKm: 60_000, rApoKm: 200_000 };
	const AWAY = { departureMode: 'orbit', systemPrimary: 'departure' } as const;
	const HOME = { arrivalMode: 'low-orbit', systemPrimary: 'target' } as const;
	const OPTIONS = { centerId: EARTH.id };

	function outbound(departureOrbit?: EndOrbit) {
		const route = buildRoute(EARTH, MOON, J2000, TOF, { ...AWAY, departureOrbit })!;
		const path = buildTrajectoryPath(EARTH, MOON, route, { ...OPTIONS, ...AWAY })!;
		return { route, path, first: path.arcs[0].points[0] };
	}

	function inbound(targetOrbit: EndOrbit) {
		const route = buildRoute(MOON, EARTH, J2000, TOF, { ...HOME, targetOrbit })!;
		const path = buildTrajectoryPath(MOON, EARTH, route, { ...OPTIONS, ...HOME })!;
		const points = path.arcs[0].points;
		return { route, path, last: points[points.length - 1] };
	}

	const ringAt = (path: TrajectoryPath, at: 'departure' | 'arrival') =>
		path.endOrbits.find((end) => end.at === at)!;

	it('leaves the orbit the trip was priced from', () => {
		const { first, route } = outbound(HIGH);
		expect(route.departureOrbit).toEqual(HIGH);
		expect(norm(first)).toBeCloseTo(HIGH.rPeriKm, 3);
	});

	it('comes home to the orbit it was priced to', () => {
		expect(norm(inbound(HIGH).last)).toBeCloseTo(HIGH.rPeriKm, 3);
	});

	it('meets its ring where it starts', () => {
		const { first, path } = outbound(HIGH);
		const ring = ringAt(path, 'departure').points;
		const gap = Math.min(...ring.map((point) => norm(sub(point, first))));
		// Half the spacing of 96 points on the ring, at most.
		expect(gap).toBeLessThan((Math.PI * HIGH.rPeriKm) / 96 + 1);
	});

	it('starts on the low point of an ellipse', () => {
		const out = outbound(ELLIPSE);
		const ring = ringAt(out.path, 'departure').points;
		expect(Math.min(...ring.map((point) => norm(sub(point, out.first))))).toBeLessThan(1);

		const back = inbound(ELLIPSE);
		const home = ringAt(back.path, 'arrival').points;
		expect(Math.min(...home.map((point) => norm(sub(point, back.last))))).toBeLessThan(1);
	});

	it('stops where the arc ends, on the way out and on the way home', () => {
		const out = outbound(HIGH);
		expect(out.path.stops.find((stop) => stop.kind === 'departure')!.r).toEqual(out.first);
		const back = inbound(HIGH);
		expect(back.path.stops.find((stop) => stop.kind === 'arrival')!.r).toEqual(back.last);
	});

	it('keeps a trip on the parking orbit as it was', () => {
		const { first, path } = outbound();
		expect(norm(first)).toBeCloseTo(parkingRadiusKm(EARTH), 3);
		const stop = path.stops.find((s) => s.kind === 'departure')!;
		expect(norm(stop.r)).toBeCloseTo(parkingRadiusKm(EARTH), 3);
		expect(norm(sub(stop.r, first))).toBeGreaterThan(0);
	});

	it('crosses a held drive from the ring, in a straight line', () => {
		const terms = { ...AWAY, departureOrbit: HIGH };
		const route = buildConstantThrustRoute(EARTH, MOON, J2000, 9.8, terms)!;
		const path = buildTrajectoryPath(EARTH, MOON, route, { ...OPTIONS, ...AWAY })!;
		expect(norm(path.arcs[0].points[0])).toBeCloseTo(HIGH.rPeriKm, 3);
	});

	it('draws a held drive in from an orbit outside the satellite', () => {
		const outside: EndOrbit = { rPeriKm: 600_000, rApoKm: 600_000 };
		const terms = { ...AWAY, departureOrbit: outside };
		const route = buildConstantThrustRoute(EARTH, MOON, J2000, 9.8, terms)!;
		const path = buildTrajectoryPath(EARTH, MOON, route, { ...OPTIONS, ...AWAY })!;
		expect(norm(path.arcs[0].points[0])).toBeCloseTo(outside.rPeriKm, 3);
		expect(buildRoute(EARTH, MOON, J2000, TOF, terms)).toBeNull();
	});
});

describe('end orbits', () => {
	/** Where an end's own lines are measured from: the body itself planet-frame,
	 *  the encounter along the crossing otherwise. */
	function originOf(end: EndOrbitPath): Vec3 {
		return end.anchorId === end.bodyId ? [0, 0, 0] : end.center;
	}

	/** Every point of `ring` is the distance from its centre a bound orbit between
	 *  the two radii would be, and it closes. Only ever true planet-frame: seen
	 *  from anywhere else a parking orbit does not close at all. */
	function checkRing(ring: EndOrbitPath, rPeriKm: number, rApoKm: number) {
		const origin = originOf(ring);
		const radii = ring.points.map((point) => norm(sub(point, origin)));
		expect(Math.min(...radii)).toBeCloseTo(rPeriKm, 3);
		expect(Math.max(...radii)).toBeCloseTo(rApoKm, 3);
		expect(ring.radiusKm).toBeCloseTo(rApoKm, 3);
		const closure = norm(sub(ring.points[0], ring.points[ring.points.length - 1]));
		expect(closure).toBeLessThan(rPeriKm * 1e-9);
	}

	/** Where the craft is at the low point of `end` — the end of the passage on
	 *  the way in, the start of it on the way out. */
	function periapsisOf(end: EndOrbitPath): Vec3 {
		return end.at === 'arrival' ? end.approach[end.approach.length - 1] : end.approach[0];
	}

	/** Earth to Mars, orbit to orbit, drawn in `frame`. The two ends are the whole
	 *  subject here and every one of them needs the same route. */
	function orbitToOrbit(frame: TrajectoryFrame = 'interplanetary') {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		return buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame })!;
	}

	it('rings both ends of a trip flown orbit to orbit', () => {
		const path = orbitToOrbit('planetary');
		expect(path.endOrbits.map((orbit) => orbit.at)).toEqual(['departure', 'arrival']);

		const [departure, arrival] = path.endOrbits;
		expect(departure.bodyId).toBe(EARTH.id);
		expect(arrival.bodyId).toBe(MARS.id);
		checkRing(departure, parkingRadiusKm(EARTH), parkingRadiusKm(EARTH));
		checkRing(arrival, parkingRadiusKm(MARS), parkingRadiusKm(MARS));
	});

	// The ring is the orbit the trip ends in, not the plane it came in on. Missed,
	// a stationary orbit draws leaning wherever the trip happened to arrive from,
	// which is the one thing it can never be.
	it('lays an orbit that names the equator flat in it, whatever plane the trip flew', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			targetOrbit: { ...parkingOrbit(MARS), incDeg: 0 }
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const arrival = path.endOrbits.find((end) => end.at === 'arrival')!;
		const pole = MARS.poleEcliptic!;
		for (const point of arrival.points) {
			expect(Math.abs(dot(point, pole))).toBeLessThan(parkingRadiusKm(MARS) * 1e-9);
		}
		// The passage is flown before the turn, so it keeps the plane it arrived in
		// — this is a burn between two planes, not one plane throughout.
		expect(Math.abs(dot(arrival.approach[0], pole))).toBeGreaterThan(1);
		// And the line still reaches the ring: it carries on past the low point to
		// the node the turn happens at, which is a point of both orbits.
		const joint = arrival.approach[arrival.approach.length - 1];
		expect(Math.abs(dot(joint, pole))).toBeLessThan(parkingRadiusKm(MARS) * 1e-9);
		expect(norm(joint)).toBeCloseTo(parkingRadiusKm(MARS), 6);
		// And it joins where the ring's own clock says it should: the turn moves the
		// low point round the orbit, it does not move the craft along it.
		const jointJd = arrival.jds[arrival.jds.length - 1];
		expect(jointJd).toBeGreaterThan(route.arriveJd);
		const nearest = arrival.pointJds!.reduce(
			(best, jd, i) =>
				Math.abs(jd - jointJd) < Math.abs(arrival.pointJds![best] - jointJd) ? i : best,
			0
		);
		// One sample of the ring covers a 96th of it, which is the whole of what
		// stands between the joint and the point that lands on it.
		expect(norm(sub(arrival.points[nearest], joint))).toBeLessThan(
			(2 * Math.PI * parkingRadiusKm(MARS)) / 96
		);
	});

	// The trip ends a revolution after it joins its final orbit, whatever phase of
	// that orbit it joins on. Counted from the ring's own clock instead, a long
	// coast to the node eats the end of the trip — and the card for the orbit it
	// ends in, dated half a revolution past the joint, lands outside the trip.
	it('flies a whole revolution of a final orbit it joins away from periapsis', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			targetOrbit: { ...parkingOrbit(MARS), incDeg: 0 }
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const arrival = path.endOrbits.find((end) => end.at === 'arrival')!;
		// The line joins the ring at the node, which is nowhere near the periapsis
		// the ring's own dates start from.
		const jointJd = arrival.jds[arrival.jds.length - 1];
		const jds = arrival.pointJds!;
		const revolution = jds[jds.length - 1] - jds[0];
		expect(jointJd - jds[0]).toBeGreaterThan(revolution / 4);
		// Every moment from there to a revolution past the trip's end, the card for
		// the final orbit among them, is on the ring.
		const settled = Math.max(route.arriveJd, jointJd);
		for (const fraction of [0, 0.25, 0.5, 0.75, 1]) {
			const at = craftPositionAt(path, jointJd + (settled + revolution - jointJd) * fraction);
			expect(at).not.toBeNull();
			expect(norm(at!.r)).toBeCloseTo(parkingRadiusKm(MARS), -1);
		}
		expect(craftPositionAt(path, settled + revolution * 1.01)).toBeNull();
	});

	// A named plane and two ends set apart at once — the Molniya case, and the only
	// orbit a trip shapes for itself. Nothing about the approach knows either
	// figure, so both have to come off the orbit that was asked for.
	it('draws an orbit that names a plane and an ellipse as both', () => {
		const rPeriKm = MARS.radiusKm + 500;
		const rApoKm = MARS.radiusKm + 20000;
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			targetOrbit: { rPeriKm, rApoKm, incDeg: 63.4 }
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const arrival = path.endOrbits.find((end) => end.at === 'arrival')!;
		const radii = arrival.points.map(norm);
		expect(Math.min(...radii)).toBeCloseTo(rPeriKm, 3);
		expect(Math.max(...radii)).toBeCloseTo(rApoKm, 3);
		// One plane throughout, leaning by the angle the trip named — measured off
		// three points of the ring rather than off the pole, which would only be
		// asking the same construction the drawing used.
		const normal = normalize(
			cross(sub(arrival.points[24], arrival.points[0]), sub(arrival.points[48], arrival.points[0]))
		);
		for (const point of arrival.points) expect(Math.abs(dot(point, normal))).toBeLessThan(1e-6);
		expect((Math.acos(Math.abs(dot(normal, MARS.poleEcliptic!))) * 180) / Math.PI).toBeCloseTo(
			63.4,
			3
		);
		// And the coast still lands on the ring, at the node the two planes share.
		const joint = arrival.approach[arrival.approach.length - 1];
		expect(Math.abs(dot(joint, normal))).toBeLessThan(1e-6);
		expect(norm(joint)).toBeGreaterThan(rPeriKm);
	});

	// The same turn run backwards: the craft is in the named plane first and turns
	// out of it, so the coast comes before the passage rather than after it.
	it('sets out from the node when the departure orbit names a plane', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			departureOrbit: { ...parkingOrbit(EARTH), incDeg: 0 }
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const departure = path.endOrbits.find((end) => end.at === 'departure')!;
		const pole = EARTH.poleEcliptic!;
		for (const point of departure.points) {
			expect(Math.abs(dot(point, pole))).toBeLessThan(parkingRadiusKm(EARTH) * 1e-9);
		}
		const joint = departure.approach[0];
		expect(Math.abs(dot(joint, pole))).toBeLessThan(parkingRadiusKm(EARTH) * 1e-9);
		expect(norm(joint)).toBeCloseTo(parkingRadiusKm(EARTH), 6);
		expect(departure.jds[0]).toBeLessThan(route.departJd);
	});

	it('names the frame each end is drawn in, so nothing has to guess', () => {
		for (const end of orbitToOrbit('interplanetary').endOrbits) {
			expect(end.anchorId).toBe(SUN);
		}
		for (const end of orbitToOrbit('planetary').endOrbits) {
			expect(end.anchorId).toBe(end.bodyId);
			// Measured off the body, so the body is the origin rather than a place
			// somewhere out along the crossing.
			expect(norm(end.points[0])).toBeLessThan(end.radiusKm * 1.001);
		}
	});

	it('draws the orbit as the trochoid it is once the frame is not the body\u2019s', () => {
		const [, arrival] = orbitToOrbit('interplanetary').endOrbits;
		const radii = arrival.points.map((point) => norm(sub(point, arrival.center)));
		// Mars covers millions of km in the time a parking orbit takes, so one
		// revolution of it is a streak along that motion rather than a ring.
		expect(Math.max(...radii)).toBeGreaterThan(arrival.radiusKm * 10);
		expect(norm(sub(arrival.points[0], arrival.points[arrival.points.length - 1]))).toBeGreaterThan(
			arrival.radiusKm
		);
		// And is still the same small orbit, which is what says whether to draw it.
		expect(arrival.radiusKm).toBeCloseTo(parkingRadiusKm(MARS), 3);
	});

	it('goes round where the bodies are on their own dates, which is where the arc meets them', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const earthAt = elementsToState(EARTH.elements, route.departJd)!;
		expect(relative(path.endOrbits[0].center, earthAt.r)).toBeLessThan(1e-9);
		expect(relative(path.endOrbits[1].center, path.meeting.r)).toBeLessThan(1e-9);
	});

	it('turns the crossing into the orbit through one shared periapsis', () => {
		// Planet-frame, where both curves are the bare conics the burn was priced
		// between and the tangency is exact rather than nearly so.
		const path = orbitToOrbit('planetary');

		for (const end of path.endOrbits) {
			const rPeri = parkingRadiusKm(end.at === 'departure' ? EARTH : MARS);
			// The passage runs between the sphere of influence and periapsis, in
			// flight order: out from the burn on the way up, down to it on the way in.
			expect(end.approach.length).toBeGreaterThan(2);
			const periapsis = periapsisOf(end);
			expect(norm(sub(periapsis, originOf(end)))).toBeCloseTo(rPeri, 3);

			// The orbit's own low point is that same place — it is drawn from
			// periapsis, so its first vertex is where the passage ends.
			expect(norm(sub(end.points[0], periapsis))).toBeLessThan(rPeri * 1e-6);

			// And the two run the same way through it, so the trip turns into its
			// orbit rather than crossing one.
			const orbitWay = normalize(sub(end.points[1], end.points[0]));
			const passageWay =
				end.at === 'arrival'
					? normalize(sub(periapsis, end.approach[end.approach.length - 2]))
					: normalize(sub(end.approach[1], end.approach[0]));
			expect(dot(orbitWay, passageWay)).toBeGreaterThan(0.999);
		}
	});

	it('hands the crossing over to the passage with no step in the line', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const points = path.arcs[0].points;
		const [departure, arrival] = path.endOrbits;

		// Each end takes a bite out of the crossing — the samples inside the sphere
		// of influence, which the passage is drawn over.
		expect(departure.trimFrom).toBeGreaterThan(0);
		expect(arrival.trimTo).toBeLessThan(points.length);

		// And picks up from the last sample left outside it, so the drawn crossing
		// and the passage are one line rather than two that nearly meet.
		const joins = norm(
			sub(departure.approach[departure.approach.length - 1], points[departure.trimFrom])
		);
		expect(joins / soiOf(EARTH, GM_SUN_KM3_S2)).toBeLessThan(1e-9);
		expect(
			norm(sub(arrival.approach[0], points[arrival.trimTo - 1])) / soiOf(MARS, GM_SUN_KM3_S2)
		).toBeLessThan(1e-9);

		// Which it can only be because the passage carries the body's own motion out
		// there: it leaves along the crossing rather than at an angle to it.
		const way = (a: Vec3, b: Vec3) => normalize(sub(b, a));
		const into = way(points[arrival.trimTo - 2], points[arrival.trimTo - 1]);
		expect(dot(into, way(arrival.approach[0], arrival.approach[1]))).toBeGreaterThan(0.99);
		const out = way(points[departure.trimFrom], points[departure.trimFrom + 1]);
		const last = departure.approach.length - 1;
		expect(dot(out, way(departure.approach[last - 1], departure.approach[last]))).toBeGreaterThan(
			0.99
		);
	});

	it('hands over where the crossing crosses the moving sphere of influence', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const arc = path.arcs[0];
		const [departure, arrival] = path.endOrbits;

		// The last sample kept on each side is still outside the sphere measured
		// against the body on that sample's own date — not against where the body
		// ends up — and the first sample dropped is inside it.
		const spheres = (body: typeof EARTH, index: number) => {
			const state = elementsToState(body.elements, arc.jds[index])!;
			return norm(sub(arc.points[index], state.r)) / soiOf(body, GM_SUN_KM3_S2);
		};
		expect(spheres(EARTH, departure.trimFrom)).toBeGreaterThanOrEqual(1);
		expect(spheres(EARTH, departure.trimFrom - 1)).toBeLessThan(1);
		expect(spheres(MARS, arrival.trimTo - 1)).toBeGreaterThanOrEqual(1);
		expect(spheres(MARS, arrival.trimTo)).toBeLessThan(1);
	});

	it('dates the arrival at the true periapsis, not the priced centre-meeting', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const [departure, arrival] = path.endOrbits;

		// The injection burn is the departure, so its date is the route's own.
		expect(departure.periJd).toBe(route.departJd);
		// The capture comes earlier than priced: the crossing is left at the
		// sphere of influence, and the fall from there beats its own last stretch
		// to the centre by hours — hours the body spends moving on.
		expect(arrival.periJd).toBeLessThan(route.arriveJd);
		expect(arrival.periJd).toBeGreaterThan(route.arriveJd - 1);
		expect(path.meeting.jd).toBe(arrival.periJd);
		// And the shifted meeting is a real place on Mars' orbit, not an offset.
		const mars = elementsToState(MARS.elements, arrival.periJd)!;
		expect(relative(arrival.center, mars.r)).toBeLessThan(1e-9);
	});

	it('leaves the crossing whole where the passage would be a step or less', () => {
		// A trip inside one system has no escape at the primary's end, so nothing is
		// taken out of that end of the arc.
		const route = buildRoute(EARTH, MOON, J2000, 5, {
			systemPrimary: 'departure',
			departureMode: 'orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MOON, route, {
			centerId: EARTH.id,
			systemPrimary: 'departure'
		})!;
		const departure = path.endOrbits.find((end) => end.at === 'departure')!;
		expect(departure.approach).toEqual([]);
		expect(departure.trimFrom).toBe(0);
		expect(departure.trimTo).toBe(path.arcs[0].points.length);
	});

	it('carries the body\u2019s own motion, so the passage is the worldline', () => {
		const path = orbitToOrbit('interplanetary');

		for (const end of path.endOrbits) {
			const body = end.at === 'departure' ? EARTH : MARS;
			const radii = end.approach.map((point) => norm(sub(point, end.center)));
			// The low point is still exactly the periapsis the burn was priced at:
			// the body has not moved from where `center` puts it at that instant, and
			// the two models' disagreement has been worked off by then.
			expect(norm(sub(periapsisOf(end), end.center))).toBeCloseTo(parkingRadiusKm(body), 6);
			// Out at the other end it carries all of the body's motion, which is why
			// that end is further out than the sphere of influence rather than on it.
			expect(Math.max(...radii)).toBeGreaterThan(soiOf(body, GM_SUN_KM3_S2));
		}
	});

	it('puts the craft in the same place in both frames, since it is the same craft', () => {
		const solar = orbitToOrbit('interplanetary');
		const planet = orbitToOrbit('planetary');

		// A frame is what positions are measured from, so the two answers differ by
		// exactly the body's motion and by nothing else. Anything more and switching
		// the frame would jump the marker — and with it a camera following it.
		for (const end of planet.endOrbits) {
			const body = end.bodyId === EARTH.id ? EARTH : MARS;
			for (let i = 0; i < end.jds.length; i++) {
				const jd = end.jds[i];
				const here = elementsToState(body.elements, jd)!.r;
				const fromBody = craftPositionAt(planet, jd)!;
				expect(fromBody.centerId).toBe(body.id);
				const fromSun = craftPositionAt(solar, jd)!;
				expect(fromSun.centerId).toBe(SUN);
				// A kilometre or so apart: the two polylines chord the same curve, and
				// the one carrying the body's motion takes longer steps to do it.
				expect(norm(sub(add(here, fromBody.r), fromSun.r))).toBeLessThan(10);
			}
		}
	});

	it('is the bare conic planet-frame, one way down and nothing carried', () => {
		const path = orbitToOrbit('planetary');

		for (const end of path.endOrbits) {
			const body = end.at === 'departure' ? EARTH : MARS;
			const radii = end.approach.map((point) => norm(sub(point, originOf(end))));
			expect(Math.min(...radii)).toBeCloseTo(parkingRadiusKm(body), 6);
			// It reaches the sphere of influence and stops there. Not exactly on it —
			// the handover is put on a sample of the crossing, so the conic runs to
			// that sample's date — but nothing carries it beyond, which is the whole
			// difference from the same passage drawn interplanetary.
			expect(Math.max(...radii)).toBeLessThan(soiOf(body, GM_SUN_KM3_S2) * 2);
			// One way down: the passage never turns back on itself.
			for (let i = 1; i < radii.length; i++) {
				const climbing = end.at === 'departure';
				expect(climbing ? radii[i] > radii[i - 1] : radii[i] < radii[i - 1]).toBe(true);
			}
		}
	});

	it('dates the passage, in flight order', () => {
		const path = orbitToOrbit('interplanetary');
		const [departure, arrival] = path.endOrbits;

		for (const end of path.endOrbits) {
			expect(end.jds).toHaveLength(end.approach.length);
			for (let i = 1; i < end.jds.length; i++) expect(end.jds[i]).toBeGreaterThan(end.jds[i - 1]);
		}
		// Each one picks up exactly where the crossing it replaces left off, and ends
		// at its own periapsis — the dates the drawn line is read by.
		expect(departure.jds[0]).toBe(departure.periJd);
		expect(departure.jds[departure.jds.length - 1]).toBeCloseTo(
			path.arcs[0].jds[departure.trimFrom],
			9
		);
		const last = path.arcs[path.arcs.length - 1];
		expect(arrival.jds[0]).toBeCloseTo(last.jds[arrival.trimTo - 1], 9);
		expect(arrival.jds[arrival.jds.length - 1]).toBe(arrival.periJd);
	});

	it('joins a held drive to the orbits at both its ends', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const [departure, arrival] = path.endOrbits;
		expect(path.endOrbits).toHaveLength(2);

		for (const end of [departure, arrival]) {
			const outward = end.at === 'departure';
			const arc = outward ? path.arcs[0] : path.arcs[path.arcs.length - 1];
			const kept = arc.points.slice(end.trimFrom, end.trimTo);
			const radius = (p: Vec3) => norm(sub(p, end.center));
			// The line goes orbit → periapsis → passage → crossing, in one piece:
			// it starts on the orbit it was priced for...
			const low = outward ? end.approach[0] : end.approach[end.approach.length - 1];
			expect(Math.min(...end.points.map((p) => norm(sub(p, low))))).toBeLessThan(1);
			expect(radius(low)).toBeLessThanOrEqual(end.radiusKm + 1);
			// ...and hands over to the crossing exactly where the crossing is cut.
			const join = outward ? end.approach[end.approach.length - 1] : end.approach[0];
			const meets = outward ? arc.points[end.trimFrom] : arc.points[end.trimTo - 1];
			expect(norm(sub(join, meets))).toBeLessThan(1);
			// So no stretch of crossing is left running into the body.
			expect(Math.min(...kept.map(radius))).toBeGreaterThan(radius(join) * 0.99);
		}

		// The climb out is flown under the drive, so it takes what that drive
		// takes rather than the fortnight a coast out to the same sphere would.
		const climb = departure.jds[departure.jds.length - 1] - departure.jds[0];
		expect(climb).toBeGreaterThan(0);
		expect(climb).toBeLessThan(3);
		// And it leaves the way the drive points — read off the body, since the
		// drawn line carries Earth's own motion, which over that long is further.
		const bare = buildTrajectoryPath(EARTH, MARS, route, {
			centerId: SUN,
			frame: 'planetary'
		})!.endOrbits[0];
		const out = bare.approach[bare.approach.length - 1];
		const dir = route.thrustDir!;
		expect(dot(normalize(out), normalize([dir[0], dir[1], dir[2]]))).toBeGreaterThan(0.9);
	});

	it('draws the loose ellipse a capture leaves the craft in', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'capture' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		// A launch from the ground gets its line but no ring — the trip does not
		// stay in the parking orbit it climbs through.
		expect(path.endOrbits.map((orbit) => orbit.at)).toEqual(['departure', 'arrival']);
		expect(path.endOrbits[0].points).toEqual([]);
		checkRing(
			path.endOrbits[1],
			parkingRadiusKm(MARS),
			travelConstants.CAPTURE_APOAPSIS_RADII * MARS.radiusKm
		);
	});

	it('runs a landing all the way to the ground', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const arrival = path.endOrbits.find((end) => end.at === 'arrival')!;
		expect(arrival.points).toEqual([]);
		// The line falls from the sphere of influence to the site: its far end is
		// out at the crossing's handover, its last sample on the surface.
		const last = arrival.approach[arrival.approach.length - 1];
		expect(norm(last)).toBeCloseTo(MARS.radiusKm, 6);
		expect(arrival.surfaceJd!).toBeGreaterThan(arrival.periJd);
		expect(arrival.jds[arrival.jds.length - 1]).toBeCloseTo(arrival.surfaceJd!, 9);
		for (let i = 1; i < arrival.jds.length; i++) {
			expect(arrival.jds[i]).toBeGreaterThan(arrival.jds[i - 1]);
		}
	});

	it('lands on the site it was given, read at touchdown', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		// A site that circles the equator like a fixed point on the spinning body.
		const spin = (jd: number): Vec3 => {
			const angle = (jd - J2000) * 2;
			return [Math.cos(angle) * MARS.radiusKm, Math.sin(angle) * MARS.radiusKm, 0];
		};
		const path = buildTrajectoryPath(EARTH, MARS, route, {
			centerId: SUN,
			frame: 'planetary',
			surfaceSites: { arrival: spin }
		})!;
		const arrival = path.endOrbits.find((end) => end.at === 'arrival')!;
		const last = arrival.approach[arrival.approach.length - 1];
		expect(relative(last, spin(arrival.surfaceJd!))).toBeLessThan(1e-9);
	});

	// Bennu-scale: the parking orbit takes days while the ground turns in hours,
	// so the site read is far too twitchy for naive re-iteration — which used to
	// date the coast past the ground and dedupe the whole fall off the line.
	it('reaches the ground of a fast-spinning small body', () => {
		const bennu = { ...MARS, id: 'spkid-20101955', radiusKm: 0.245, mu: 4.9e-9, hillKm: 31 };
		const route = buildRoute(EARTH, bennu, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const spinRad = (2 * Math.PI) / (4.3 / 24);
		const spin = (jd: number): Vec3 => {
			const angle = (jd - J2000) * spinRad;
			return [Math.cos(angle) * bennu.radiusKm, Math.sin(angle) * bennu.radiusKm, 0];
		};
		const path = buildTrajectoryPath(EARTH, bennu, route, {
			centerId: SUN,
			frame: 'planetary',
			surfaceSites: { arrival: spin }
		})!;
		const arrival = path.endOrbits.find((end) => end.at === 'arrival')!;
		const last = arrival.approach[arrival.approach.length - 1];
		expect(norm(last)).toBeCloseTo(bennu.radiusKm, 6);
		expect(relative(last, spin(arrival.surfaceJd!))).toBeLessThan(1e-6);
		expect(arrival.jds[arrival.jds.length - 1]).toBeCloseTo(arrival.surfaceJd!, 9);
		for (let i = 1; i < arrival.jds.length; i++) {
			expect(arrival.jds[i]).toBeGreaterThan(arrival.jds[i - 1]);
		}
	});

	it('climbs off the ground before it leaves', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { departureMode: 'surface' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const departure = path.endOrbits.find((end) => end.at === 'departure')!;
		expect(norm(departure.approach[0])).toBeCloseTo(EARTH.radiusKm, 6);
		expect(departure.surfaceJd!).toBeLessThan(departure.periJd);
		expect(departure.jds[0]).toBeCloseTo(departure.surfaceJd!, 9);
		for (let i = 1; i < departure.jds.length; i++) {
			expect(departure.jds[i]).toBeGreaterThan(departure.jds[i - 1]);
		}
	});

	it('anchors a borrowed end to its own body, not to the ancestor it flies as', () => {
		// A Moon-sized body on Earth's orbit: the crossing is right to start at the
		// ancestor's position, but the ground and the orbit at that end belong to
		// the live body, which is nowhere near it.
		const moon = {
			...EARTH,
			id: 'naif-301',
			radiusKm: 1737.4,
			mu: 4902.8,
			borrowedElements: true
		};
		const route = buildRoute(moon, MARS, MARS_WINDOW, MARS_TOF, { departureMode: 'surface' })!;
		const path = buildTrajectoryPath(moon, MARS, route, { centerId: SUN })!;
		const departure = path.endOrbits.find((end) => end.at === 'departure')!;
		expect(departure.anchorId).toBe('naif-301');
		// Body-relative, from the ground up through the body's own escape
		// hyperbola, with the crossing trimmed where the passage takes over.
		expect(norm(departure.approach[0])).toBeCloseTo(moon.radiusKm, 6);
		const tip = departure.approach[departure.approach.length - 1];
		expect(norm(tip)).toBeGreaterThan(moon.radiusKm * 10);
		expect(departure.trimFrom).toBeGreaterThan(0);
	});

	it('has nothing to draw at an end the craft flies past', () => {
		const flyby = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'flyby' })!;
		const path = buildTrajectoryPath(EARTH, MARS, flyby, { centerId: SUN })!;
		expect(path.endOrbits.map((orbit) => orbit.at)).toEqual(['departure']);
	});

	it('rings the primary at its own centre, where the frame is already anchored', () => {
		const route = buildRoute(EARTH, MOON, J2000, 5, {
			systemPrimary: 'departure',
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MOON, route, {
			centerId: EARTH.id,
			systemPrimary: 'departure',
			frame: 'planetary'
		})!;
		const [departure, arrival] = path.endOrbits;
		expect(norm(departure.center)).toBe(0);
		// And the Moon's, out where the Moon is when the craft gets there.
		expect(norm(arrival.center)).toBeGreaterThan(300_000);
		checkRing(arrival, parkingRadiusKm(MOON), parkingRadiusKm(MOON));
	});

	it('lays the orbit and its passage in one plane, planet-frame', () => {
		for (const end of orbitToOrbit('planetary').endOrbits) {
			const origin = originOf(end);
			const quarter = end.points[Math.floor(end.points.length / 4)];
			const normal = normalize(cross(sub(end.points[0], origin), sub(quarter, origin)));
			// The orbit is a conic and nothing else. The passage is that too, plus the
			// kilometres the two solvers disagree by where it meets the crossing — so
			// it leaves the plane by a few km on a curve a million km long, and by
			// nothing that would read as a second plane.
			for (const point of end.points) {
				const from = sub(point, origin);
				expect(Math.abs(dot(from, normal)) / norm(from)).toBeLessThan(1e-9);
			}
			for (const point of end.approach) {
				expect(Math.abs(dot(sub(point, origin), normal))).toBeLessThan(end.radiusKm * 0.01);
			}
		}
	});

	it('lets the passage leave that plane once it carries the body\u2019s motion', () => {
		for (const end of orbitToOrbit('interplanetary').endOrbits) {
			// The orbit's plane, read off the passage instead: the drawn ring is a
			// trochoid in this frame and no longer has one of its own.
			const low = end.at === 'departure' ? end.approach[0] : end.approach[end.approach.length - 1];
			const next = end.at === 'departure' ? end.approach[1] : end.approach[end.approach.length - 2];
			const normal = normalize(cross(sub(low, end.center), sub(next, end.center)));
			// In the plane at the low point, out of it at the far end — because the
			// body's own motion is not in it, and out there that is most of the line.
			const outOfPlane = (point: Vec3) => Math.abs(dot(sub(point, end.center), normal));
			const far = end.at === 'departure' ? end.approach[end.approach.length - 1] : end.approach[0];
			expect(outOfPlane(low)).toBeLessThan(1);
			expect(outOfPlane(far)).toBeGreaterThan(1000);
		}
	});
});

describe('arc dates', () => {
	/** Every arc of `path` has a date per sample, increasing, spanning the arc. */
	function checkDates(path: ReturnType<typeof buildTrajectoryPath>) {
		for (const arc of path!.arcs) {
			expect(arc.jds).toHaveLength(arc.points.length);
			expect(arc.jds[0]).toBeCloseTo(arc.startJd, 6);
			expect(arc.jds[arc.jds.length - 1]).toBeCloseTo(arc.endJd, 6);
			for (let i = 1; i < arc.jds.length; i++) {
				expect(arc.jds[i]).toBeGreaterThan(arc.jds[i - 1]);
			}
		}
	}

	it('dates a coasting transfer', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
		checkDates(buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN }));
	});

	it('dates both halves of a held drive', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1)!;
		checkDates(buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN }));
	});

	it('dates a system transfer, which is sampled in angle rather than in time', () => {
		const route = buildRoute(EARTH, MOON, J2000, 5, { systemPrimary: 'departure' })!;
		const path = buildTrajectoryPath(EARTH, MOON, route, {
			centerId: EARTH.id,
			systemPrimary: 'departure'
		});
		checkDates(path);

		// Climbing away from periapsis it is fastest at the start, so by half the
		// time it is past half the samples. Even spacing would put it at exactly
		// half, which is the bug these dates exist to avoid.
		const arc = path!.arcs[0];
		const half = (arc.startJd + arc.endJd) / 2;
		const reached = arc.jds.filter((jd) => jd <= half).length;
		expect(reached).toBeGreaterThan(arc.jds.length * 0.5);
	});
});

describe('craftPositionAt', () => {
	const ROUTE = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
	const PATH = buildTrajectoryPath(EARTH, MARS, ROUTE, { centerId: SUN })!;

	it('starts on the departure and ends in the orbit it was sold', () => {
		// On the parking orbit the launch climbs through, not at the body's centre.
		const start = craftPositionAt(PATH, ROUTE.departJd)!.r;
		expect(norm(sub(start, PATH.stops[0].r))).toBeCloseTo(parkingRadiusKm(EARTH), 0);
		// Not on the arrival stop: that is the crossing reaching Mars' centre, a
		// place the craft never goes. The line ends at the periapsis the insertion
		// burn is made at; by the priced arrival, hours later, the craft has moved
		// on round the orbit it was sold.
		const arrival = PATH.endOrbits.find((end) => end.at === 'arrival')!;
		const last = arrival.approach[arrival.approach.length - 1];
		const lineEnd = arrival.jds[arrival.jds.length - 1];
		expect(relative(craftPositionAt(PATH, lineEnd)!.r, last)).toBeLessThan(1e-9);
		const at = craftPositionAt(PATH, ROUTE.arriveJd)!.r;
		let step = 0;
		for (let i = 1; i < arrival.points.length; i++) {
			step = Math.max(step, norm(sub(arrival.points[i], arrival.points[i - 1])));
		}
		let gap = Infinity;
		for (const point of arrival.points) gap = Math.min(gap, norm(sub(at, point)));
		expect(gap).toBeLessThan(step);
	});

	it('rides the drawn passage rather than the arc it replaces', () => {
		const arrival = PATH.endOrbits.find((end) => end.at === 'arrival')!;
		const arc = PATH.arcs[PATH.arcs.length - 1];
		const handover = arc.jds[arrival.trimTo - 1];
		// Read off the untrimmed conic the craft closes on the body's centre in a
		// straight line while the drawn line curves away; every sample has to sit on
		// what is actually drawn instead.
		for (let i = 0; i <= 8; i++) {
			const jd = handover + ((arrival.periJd - handover) * i) / 8;
			const at = craftPositionAt(PATH, jd)!.r;
			let gap = Infinity;
			for (const point of arrival.approach) gap = Math.min(gap, norm(sub(at, point)));
			// Within a sample step of the line, which is all a polyline can promise.
			expect(gap).toBeLessThan(arrival.radiusKm);
		}
	});

	it('rides each end orbit for one revolution, and is gone beyond them', () => {
		expect(craftPositionAt(PATH, ROUTE.departJd - 1)).toBeNull();
		// After the trip's line ends the craft stays on the drawn revolution of
		// the orbit it was sold — that is where a "final orbit" pick lands — and
		// only past that is there nothing left to place.
		const arrival = PATH.endOrbits.find((end) => end.at === 'arrival')!;
		const jds = arrival.pointJds!;
		const revolution = jds[jds.length - 1] - jds[0];
		expect(revolution).toBeGreaterThan(0);
		expect(craftPositionAt(PATH, ROUTE.arriveJd + revolution - 0.01)).not.toBeNull();
		expect(craftPositionAt(PATH, ROUTE.arriveJd + revolution + 0.01)).toBeNull();
	});

	it('rides the climb from liftoff, hours before the priced departure', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { departureMode: 'surface' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const departure = path.endOrbits.find((end) => end.at === 'departure')!;
		const at = craftPositionAt(path, departure.surfaceJd!)!;
		expect(at.centerId).toBe(departure.anchorId);
		expect(relative(at.r, departure.approach[0])).toBeLessThan(1e-9);
	});

	it('moves along the arc, and only forwards', () => {
		let previous = craftPositionAt(PATH, ROUTE.departJd)!.r;
		let travelled = 0;
		for (let i = 1; i <= 40; i++) {
			const at = craftPositionAt(PATH, ROUTE.departJd + (ROUTE.tofDays * i) / 40)!.r;
			expect(at).not.toBeNull();
			travelled += norm(sub(at, previous));
			previous = at;
		}
		// It got there the long way round, not by sitting still.
		expect(travelled).toBeGreaterThan(norm(sub(PATH.stops[1].r, PATH.stops[0].r)));
	});

	it('follows the clock on a held drive, not the ruler', () => {
		// Distance under constant thrust goes as ½at², so a quarter of the way
		// through the trip is about an eighth of the way along — reading the samples
		// by index would put it at a quarter. Loose bounds because the arc is flown
		// under the Sun rather than ruled straight, so the fractions are no longer
		// exactly the textbook ones.
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1)!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const start = path.stops[0].r;
		const end = path.stops[1].r;
		const total = norm(sub(end, start));
		const quarter = craftPositionAt(path, route.departJd + route.tofDays / 4)!.r;
		const alongAtQuarter = norm(sub(quarter, start)) / total;
		expect(alongAtQuarter).toBeGreaterThan(0.05);
		expect(alongAtQuarter).toBeLessThan(0.2);
		// And the flip is still near the middle of the crossing, as the pricing
		// assumes — both burns are the same length.
		const flip = craftPositionAt(path, route.departJd + route.tofDays / 2)!.r;
		expect(norm(sub(flip, start)) / total).toBeCloseTo(0.5, 1);
	});

	it('hands a swing-by crossing to the arc it is on', () => {
		const path = buildTrajectoryPath(EARTH, JUPITER, ASSIST_ROUTE, {
			centerId: SUN,
			vias: [VENUS]
		})!;
		const flyby = ASSIST_ROUTE.flybys![0];
		const at = craftPositionAt(path, flyby.jd)!.r;
		// Mid-pass the craft rides the passage arc, well inside the sphere of
		// influence of the body it is swinging past.
		const venusAt = elementsToState(VENUS.elements, flyby.jd)!.r;
		expect(norm(sub(at, venusAt))).toBeLessThan(soiOf(VENUS, GM_SUN_KM3_S2));
	});
});

describe('pathViewpoint', () => {
	const ROUTE = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF)!;
	const PATH = buildTrajectoryPath(EARTH, MARS, ROUTE, { centerId: SUN })!;

	/** Distance from `point` to the nearest sample of any arc, km. */
	function offArc(point: Vec3): number {
		let best = Infinity;
		for (const arc of PATH.arcs) {
			for (const sample of arc.points) best = Math.min(best, norm(sub(point, sample)));
		}
		return best;
	}

	it('lands a stretch in the middle of the arc that covers it', () => {
		const view = pathViewpoint(PATH, ROUTE.departJd, ROUTE.arriveJd)!;
		expect(view).not.toBeNull();
		expect(offArc(view.r)).toBe(0);
		// Actually in the middle, not at either end where the bodies are.
		const arc = PATH.arcs[0];
		expect(norm(sub(view.r, arc.points[0]))).toBeGreaterThan(1e7);
		expect(norm(sub(view.r, arc.points[arc.points.length - 1]))).toBeGreaterThan(1e7);
	});

	it('lands an instant on the stop it names', () => {
		for (const stop of PATH.stops) {
			const view = pathViewpoint(PATH, stop.jd, stop.jd)!;
			expect(view.r).toEqual(stop.r);
		}
	});

	it('picks the arc a swing-by leg belongs to, not the other one', () => {
		const path = buildTrajectoryPath(EARTH, JUPITER, ASSIST_ROUTE, {
			centerId: SUN,
			vias: [VENUS]
		})!;
		const flyby = ASSIST_ROUTE.flybys![0];
		const first = pathViewpoint(path, ASSIST_ROUTE.departJd, flyby.jd)!;
		const second = pathViewpoint(path, flyby.jd, ASSIST_ROUTE.arriveJd)!;
		expect(first.r).toEqual(path.arcs[0].points[Math.floor(path.arcs[0].points.length / 2)]);
		expect(second.r).toEqual(path.arcs[2].points[Math.floor(path.arcs[2].points.length / 2)]);
	});

	it('has nowhere to point on a path with no arcs', () => {
		expect(pathViewpoint({ ...PATH, arcs: [] }, ROUTE.departJd, ROUTE.arriveJd)).toBeNull();
	});

	it('lands a surface end’s instant on the ground, not on the priced stop', () => {
		// The stop is the body's centre at the priced date — somewhere the live
		// planet has moved on from by touchdown, and a pivot the camera could
		// never close on the planet from.
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		for (const end of path.endOrbits) {
			const view = pathViewpoint(path, end.surfaceJd!, end.surfaceJd!)!;
			const tip = end.approach[end.at === 'departure' ? 0 : end.approach.length - 1];
			expect(view.r).toEqual(tip);
		}
	});
});

describe('aero-assisted arrivals', () => {
	const radiusAbout = (end: { center: Vec3 }, p: Vec3) => norm(sub(p, end.center));

	it('flies an aerocapture pass at the entry interface and coasts out to the trim burn', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		})!;
		// The pass and the engine's raise are their own steps, in flight order.
		expect(route.legs.slice(-2).map((l) => l.kind)).toEqual(['aero-pass', 'raise']);
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;

		// The lowest point of the line is the pass, in the air — not the parking
		// orbit the trip was priced into.
		// Within the seam correction's reach: the fall works off the two solvers'
		// disagreement on the way down, so periapsis is only exact to that blend.
		const rEntry = aeroPassRadiusKm(MARS);
		const low = Math.min(...end.approach.map((p) => radiusAbout(end, p)));
		expect(low).toBeLessThan(parkingRadiusKm(MARS) - 100);
		expect(Math.abs(low - rEntry)).toBeLessThan(100);

		// Past periapsis the line keeps flying: out to apoapsis of the post-pass
		// ellipse, where the trim burn hands over to the priced orbit.
		expect(end.jds[end.jds.length - 1]).toBeGreaterThan(end.periJd);
		const last = end.approach[end.approach.length - 1];
		expect(radiusAbout(end, last)).toBeCloseTo(parkingRadiusKm(MARS), -1);

		// The dip below the shell is marked for the overlay to composite under
		// the atmosphere's glow.
		expect(end.ground!.length).toBeGreaterThan(0);
	});

	// The campaign is flown in the plane the pass entered in, so a named plane is
	// still owed a turn when it is over. Missed, the orbit the trip ends in leans
	// with the approach — the whole of what an equatorial orbit cannot do.
	it('turns into a named plane after the campaign, not never', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			arrivalMode: 'low-orbit',
			aero: 'aerobraking',
			targetOrbit: { ...parkingOrbit(MARS), incDeg: 0 }
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;
		const pole = MARS.poleEcliptic!;
		for (const point of end.points) {
			expect(Math.abs(dot(point, pole))).toBeLessThan(parkingRadiusKm(MARS) * 1e-9);
		}
		// The revolutions before it are not in that plane, or there would be
		// nothing to turn.
		const campaign = end.approach.slice(0, end.turn!.from);
		expect(Math.max(...campaign.map((p) => Math.abs(dot(p, pole))))).toBeGreaterThan(1);
		// And the coast leaves the campaign where it ends, at apoapsis, for the
		// node where the two planes meet.
		const joint = end.approach[end.approach.length - 1];
		expect(norm(end.approach[end.turn!.from])).toBeCloseTo(parkingRadiusKm(MARS), -1);
		expect(Math.abs(dot(joint, pole))).toBeLessThan(parkingRadiusKm(MARS) * 1e-9);
		expect(norm(joint)).toBeCloseTo(parkingRadiusKm(MARS), 6);
	});

	it('draws an aerobraking campaign as revolutions drag walks down, on the campaign dates', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			arrivalMode: 'low-orbit',
			aero: 'aerobraking'
		})!;
		const campaign = route.legs.find((l) => l.kind === 'aerobrake')!.days;
		expect(campaign).toBeGreaterThan(30);
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;

		// Capture goes out to the loose ellipse the engine burned into, then the
		// campaign brings the line back down to the priced orbit. Only the part
		// past periapsis is the campaign; before it is the passage, SOI-scale.
		const rApoLoose = travelConstants.CAPTURE_APOAPSIS_RADII * MARS.radiusKm;
		const after = end.approach.filter((_, i) => end.jds[i] > end.periJd + 1e-6);
		const high = Math.max(...after.map((p) => radiusAbout(end, p)));
		expect(high).toBeCloseTo(rApoLoose, -3);
		const last = end.approach[end.approach.length - 1];
		expect(radiusAbout(end, last)).toBeCloseTo(parkingRadiusKm(MARS), -1);

		// The revolutions are spread over the campaign's real dates, so the
		// craft is on them mid-campaign.
		const span = end.jds[end.jds.length - 1] - end.periJd;
		expect(span).toBeGreaterThan(campaign);
		expect(span).toBeLessThan(campaign * 1.5);
		const mid = craftPositionAt(path, end.periJd + campaign / 2)!;
		expect(mid).not.toBeNull();
		const rMid = norm(sub(mid.r, end.center));
		expect(rMid).toBeGreaterThan(aeroPassRadiusKm(MARS) - 1);
		expect(rMid).toBeLessThan(travelConstants.CAPTURE_APOAPSIS_RADII * MARS.radiusKm + 1);

		// Every dip into the air is its own stretch for the overlay.
		expect(end.ground!.length).toBeGreaterThan(2);
	});

	it('runs a direct entry from the pass to the ground with no parking coast', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			arrivalMode: 'landing',
			aero: 'aerocapture'
		})!;
		// A direct entry never enters an orbit, so there is no insertion to list.
		expect(route.legs.find((l) => l.kind === 'capture')).toBeUndefined();
		// Planet-frame, so the descent's carried motion drops out and a sample's
		// norm is its altitude.
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;

		expect(end.surfaceJd).toBeDefined();
		expect(end.points).toHaveLength(0);
		// The passage crosses the parking radius on its way down, but nothing
		// rides it: no run of samples holds that altitude the way a coast would.
		const rPark = parkingRadiusKm(MARS);
		const atParking = end.approach.map(norm).filter((r) => Math.abs(r - rPark) < 3);
		expect(atParking.length).toBeLessThanOrEqual(2);
		// The skim it rides instead is the pass, at the entry interface.
		const rEntry = aeroPassRadiusKm(MARS);
		const skim = end.approach.map(norm).filter((r) => r < rEntry + 5 && r > MARS.radiusKm + 5);
		expect(skim.length).toBeGreaterThan(5);
		expect(norm(end.approach[end.approach.length - 1])).toBeCloseTo(MARS.radiusKm, 0);
	});

	it('keeps the craft going round the final orbit after the pass', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, {
			centerId: SUN,
			frame: 'planetary'
		})!;
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;
		const apoJd = end.jds[end.jds.length - 1];
		// The ring's clock starts at its periapsis, half a revolution after the
		// line hands over at apoapsis; the wrap carries the half between.
		const settle = end.pointJds![0];
		expect(settle).toBeGreaterThan(apoJd);
		const midway = craftPositionAt(path, (apoJd + settle) / 2)!;
		expect(norm(midway.r)).toBeCloseTo(parkingRadiusKm(MARS), -1);
		// A revolution of the orbit past the handover, counted from where the line
		// joins it rather than from the ring's own clock.
		const jds = end.pointJds!;
		const revolution = jds[jds.length - 1] - jds[0];
		expect(craftPositionAt(path, apoJd + revolution - 0.001)).not.toBeNull();
		expect(craftPositionAt(path, apoJd + revolution + 0.001)).toBeNull();
	});

	it('draws the arrival propulsively when the body ignored the request', () => {
		const dryMars = { ...MARS, aeroPressurePa: undefined, aeroScaleHeightKm: undefined };
		const route = buildRoute(EARTH, dryMars, MARS_WINDOW, MARS_TOF, {
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		})!;
		expect(route.legs.at(-1)!.kind).toBe('capture');
		expect(route.legs.some((l) => l.aerobraked)).toBe(false);
		const path = buildTrajectoryPath(EARTH, dryMars, route, { centerId: SUN })!;
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;
		// The passage ends at the priced periapsis, like any engine capture.
		expect(end.jds[end.jds.length - 1]).toBeCloseTo(end.periJd, 6);
	});
});

describe('a crossing between two systems', () => {
	const SSB = 'naif-0';

	/** A star at `km` from the barycentre, met as the end itself. */
	function star(id: string, km: Vec3): SystemEnd {
		return {
			body: {
				id,
				mu: GM_SUN_KM3_S2,
				muEstimated: true,
				radiusKm: 700_000,
				elements: { a: 0, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0, epoch: J2000 }
			},
			starKm: km,
			starMu: GM_SUN_KM3_S2,
			atStar: true
		};
	}

	const HOME: SystemEnd = { body: EARTH, starKm: [0, 0, 0], starMu: GM_SUN_KM3_S2, atStar: false };
	const TAU_CETI = star('x-21238067', [7 * LIGHT_YEAR_KM, -9 * LIGHT_YEAR_KM, 3.6 * LIGHT_YEAR_KM]);
	const PROXIMA = star('x-27424668', [
		-1.5 * LIGHT_YEAR_KM,
		3.9 * LIGHT_YEAR_KM,
		-0.6 * LIGHT_YEAR_KM
	]);

	function torch(coastFraction: number, arrivalMode: 'rendezvous' | 'flyby' = 'rendezvous') {
		return buildInterstellarTorchRoute(HOME, TAU_CETI, J2000, 1.5 * G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode,
			coastFraction
		})!;
	}

	/** The path of a trip from home to Tau Ceti. */
	function drawn(route: Route) {
		return buildTrajectoryPath(EARTH, TAU_CETI.body, route, {
			centerId: SSB,
			systems: { origin: HOME, target: TAU_CETI }
		})!;
	}

	/** Where the craft is along the line, as a share of the whole crossing. */
	function share(path: NonNullable<ReturnType<typeof buildTrajectoryPath>>, jd: number): number {
		const start = path.arcs[0].points[0];
		const end = path.meeting.r;
		const at = craftPositionAt(path, jd)!.r;
		return dot(sub(at, start), sub(end, start)) / dot(sub(end, start), sub(end, start));
	}

	it('runs straight between its two ends, exactly on the two places', () => {
		const route = torch(0);
		const path = drawn(route);
		const { originKm: start, targetKm } = heldLine(HOME, TAU_CETI, route);
		expect(path.arcs[0].points[0]).toEqual(start);
		expect(path.arcs.at(-1)!.points.at(-1)).toEqual(targetKm);
		expect(path.meeting.r).toEqual(targetKm);
		expect(path.stops.map((stop) => stop.bodyId)).toEqual([EARTH.id, TAU_CETI.body.id]);
		// Every sample is on the line between the two ends.
		const axis = normalize(sub(TAU_CETI.starKm, start));
		for (const arc of path.arcs) {
			for (const point of arc.points) {
				expect(norm(cross(sub(point, start), axis)) / LIGHT_YEAR_KM).toBeLessThan(1e-9);
			}
		}
	});

	it('marks the boost and the brake of a stop, and flips half way', () => {
		const route = torch(0);
		const path = drawn(route);
		expect(path.arcs.map((arc) => arc.kind)).toEqual(['boost', 'brake']);
		const [boost, brake] = path.arcs;
		expect(relative(boost.points.at(-1)!, brake.points[0])).toBeLessThan(1e-15);
		expect(norm(boost.points.at(-1)!) / norm(TAU_CETI.starKm)).toBeCloseTo(0.5, 5);
		// The arcs end on the dates of their legs, which the timeline reads.
		const boostLeg = route.legs.find((leg) => leg.kind === 'boost')!;
		expect(boost.startJd).toBe(route.departJd);
		expect(boost.endJd).toBe(route.departJd + boostLeg.days);
		expect(brake.endJd).toBe(route.arriveJd);
		expect(share(path, boost.endJd)).toBeCloseTo(0.5, 6);
	});

	it('marks the coast between the burns', () => {
		const path = drawn(torch(0.25));
		expect(path.arcs.map((arc) => arc.kind)).toEqual(['boost', 'cruise', 'brake']);
	});

	it('never brakes on a flyby', () => {
		expect(drawn(torch(0, 'flyby')).arcs.map((arc) => arc.kind)).toEqual(['boost']);
		expect(drawn(torch(0.25, 'flyby')).arcs.map((arc) => arc.kind)).toEqual(['boost', 'cruise']);
	});

	it('dates the line by the relativistic motion along it', () => {
		const route = torch(0.25);
		const path = drawn(route);
		for (const arc of path.arcs) {
			for (let i = 1; i < arc.jds.length; i++) expect(arc.jds[i]).toBeGreaterThan(arc.jds[i - 1]);
		}
		const totalKm = route.interstellar!.distanceKm;
		for (const part of [0.01, 0.1, 0.3, 0.5, 0.8, 0.97]) {
			const jd = route.departJd + crossingElapsed(route, part * totalKm)!.days;
			expect(share(path, jd)).toBeCloseTo(part, 3);
		}
		expect(craftPositionAt(path, route.departJd - 1)).toBeNull();
		expect(craftPositionAt(path, route.arriveJd + 1)).toBeNull();
	});

	it('draws a coast as cruise arcs that span one leg, at an even pace', () => {
		const route = buildInterstellarCruiseRoute(
			HOME,
			TAU_CETI,
			J2000,
			{ kind: 'budget', dvKms: 41 },
			{ departureMode: 'orbit', arrivalMode: 'flyby' }
		);
		if (typeof route !== 'object' || route === null) throw new Error('no coast');
		const path = drawn(route);
		expect(path.arcs.map((arc) => arc.kind)).toEqual(['cruise', 'cruise', 'cruise']);
		expect(path.arcs[0].startJd).toBe(route.departJd);
		expect(path.arcs.at(-1)!.endJd).toBe(route.arriveJd);
		const middle = (route.departJd + route.arriveJd) / 2;
		expect(share(path, middle)).toBeCloseTo(0.5, 5);
	});

	it('measures a trip between two other stars from the star it leaves', () => {
		const route = buildInterstellarTorchRoute(PROXIMA, TAU_CETI, J2000, G0_M_S2, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		})!;
		const path = buildTrajectoryPath(PROXIMA.body, TAU_CETI.body, route, {
			centerId: PROXIMA.body.id,
			centerKm: PROXIMA.starKm,
			systems: { origin: PROXIMA, target: TAU_CETI }
		})!;
		expect(path.centerId).toBe(PROXIMA.body.id);
		const gapKm = sub(TAU_CETI.starKm, PROXIMA.starKm);
		expect(path.arcs[0].points[0]).toEqual(scale(normalize(gapKm), AU_KM));
		expect(norm(sub(path.meeting.r, gapKm)) / AU_KM).toBeCloseTo(1, 6);
	});
});

describe('the ends of a crossing', () => {
	const SSB = 'naif-0';
	const ORIGIN: Vec3 = [0, 0, 0];

	function starEnd(id: string, starKm: Vec3, massSolar = 1): SystemEnd {
		return {
			body: {
				id,
				mu: massSolar * GM_SUN_KM3_S2,
				muEstimated: true,
				radiusKm: 700_000,
				elements: { a: 0, e: 0, i: 0, om: 0, w: 0, ma: 0, n: 0, epoch: J2000 }
			},
			starKm,
			starMu: massSolar * GM_SUN_KM3_S2,
			atStar: true
		};
	}

	/** A rocky planet with air on a tilted orbit of `star`. */
	function planetOf(star: SystemEnd, name: string, aAu: number): SystemEnd {
		const n = (Math.sqrt(star.starMu! / (aAu * AU_KM) ** 3) * SEC_PER_DAY * 180) / Math.PI;
		const elements = { a: aAu, e: 0.05, i: 20, om: 40, w: 50, ma: 60, n, epoch: J2000 };
		const body = {
			id: `${star.body.id}-${name}`,
			mu: 4e5,
			muEstimated: true,
			radiusKm: 6_500,
			aeroPressurePa: 100_000,
			elements,
			parentId: star.body.id
		};
		return { ...star, body, atStar: false };
	}

	const HOME: SystemEnd = { body: EARTH, starKm: ORIGIN, starMu: GM_SUN_KM3_S2, atStar: false };
	const AT_MARS: SystemEnd = { ...HOME, body: MARS };
	const AT_MOON: SystemEnd = {
		...HOME,
		body: { ...MOON, elements: EARTH.elements, borrowedElements: true },
		wells: [{ mu: EARTH.mu, radiusKm: MOON.elements.a * AU_KM }]
	};
	const SUN_END = starEnd(SUN, ORIGIN);
	const FAR = starEnd('x-1', [3 * LIGHT_YEAR_KM, 2.2 * LIGHT_YEAR_KM, 1.1 * LIGHT_YEAR_KM], 0.5);
	const FAR_PLANET = planetOf(FAR, 'b', 0.2);
	/** The two stars of a binary, 23 au apart. */
	const ALPHA = starEnd('x-2', [-2 * LIGHT_YEAR_KM, 3 * LIGHT_YEAR_KM, -1 * LIGHT_YEAR_KM], 1.1);
	const BETA = starEnd('x-3', add(ALPHA.starKm, [23 * AU_KM, 0, 0]), 0.9);

	const RING = { rPeriKm: 2 * AU_KM, rApoKm: 3 * AU_KM };
	const MOLNIYA = { rPeriKm: 7_000, rApoKm: 46_000, incDeg: 63.4, argPeriDeg: 270 };
	const STATION = { rPeriKm: 7_000, rApoKm: 7_000, incDeg: 51.6 };

	type Terms = InterstellarCruiseOptions;
	type Drive = 'coast' | 'held';
	const DRIVES: Drive[] = ['coast', 'held'];
	const FRAMES: TrajectoryFrame[] = ['interplanetary', 'planetary'];

	/** The route of `drive`, or the reason it has none. */
	function fly(drive: Drive, from: SystemEnd, to: SystemEnd, terms: Terms) {
		return drive === 'held'
			? buildInterstellarTorchRoute(from, to, J2000, G0_M_S2, terms)
			: buildInterstellarCruiseRoute(from, to, J2000, { kind: 'budget', dvKms: 600 }, terms);
	}

	function trip(drive: Drive, from: SystemEnd, to: SystemEnd, terms: Terms): Route {
		const route = fly(drive, from, to, terms);
		if (route === null || typeof route === 'string') throw new Error(`no route: ${route}`);
		return route;
	}

	function draw(
		from: SystemEnd,
		to: SystemEnd,
		route: Route,
		options: Partial<Parameters<typeof buildTrajectoryPath>[3]> = {}
	) {
		const path = buildTrajectoryPath(from.body, to.body, route, {
			centerId: SSB,
			systems: { origin: from, target: to },
			...options
		});
		if (!path) throw new Error('no path');
		return path;
	}

	type Path = ReturnType<typeof draw>;

	const inSameSystem = (a: SystemEnd, b: SystemEnd) => norm(sub(a.starKm, b.starKm)) === 0;
	const endAt = (path: Path, at: EndOrbitPath['at']) => path.endOrbits.find((e) => e.at === at);

	/** What the line of an end has to reach. `conic` says the arc stops at a pass. */
	function expectAtEnd(
		point: Vec3,
		end: SystemEnd,
		jd: number,
		passKm: number | null,
		name: string
	) {
		const place = endPlaceKm(end, jd);
		if (passKm === null) expect(norm(sub(point, place)), name).toBeLessThan(0.1);
		else expect(norm(sub(point, place)) / passKm, name).toBeCloseTo(1, 3);
	}

	function expectWhole(path: Path, route: Route, from: SystemEnd, to: SystemEnd, name: string) {
		const { arcs, endOrbits, frame } = path;
		expect(arcs[0].startJd, name).toBe(route.departJd);
		expect(arcs.at(-1)!.endJd, name).toBe(route.arriveJd);
		expect(path.stops[0].r, name).toEqual(arcs[0].points[0]);
		expect(path.stops[1].r, name).toEqual(arcs.at(-1)!.points.at(-1));

		let lastJd = -Infinity;
		arcs.forEach((arc, index) => {
			expect(arc.jds.length, name).toBe(arc.points.length);
			if (index > 0) {
				expect(arc.jds[0], name).toBe(lastJd);
				expect(arc.points[0], name).toEqual(arcs[index - 1].points.at(-1));
			} else lastJd = arc.jds[0] - 1;
			for (const [i, jd] of arc.jds.entries()) {
				if (i > 0) expect(jd, name).toBeGreaterThan(arc.jds[i - 1]);
				expect(jd, name).toBeGreaterThanOrEqual(lastJd);
			}
			lastJd = arc.jds.at(-1)!;
			// A trim never eats the arc.
			const { from: kept, to: stop } = crossingWindow(path, index);
			expect(stop - kept, name).toBeGreaterThanOrEqual(2);
		});

		for (const end of endOrbits) {
			const body = end.at === 'departure' ? from.body : to.body;
			const anchored = frame === 'planetary' || body.borrowedElements === true;
			expect(end.anchorId, name).toBe(anchored ? body.id : path.centerId);
			expect(end.jds.length, name).toBe(end.approach.length);
			for (let i = 1; i < end.jds.length; i++) {
				expect(end.jds[i], name).toBeGreaterThan(end.jds[i - 1]);
			}
			for (const point of [...end.approach, ...end.points]) {
				expect(Number.isFinite(norm(point)), name).toBe(true);
			}
			if (end.surfaceJd === undefined) {
				expect(end.points.length, name).toBeGreaterThan(2);
				// Closed in the frame of the body, a trochoid outside it.
				if (anchored) expect(relative(end.points[0], end.points.at(-1)!), name).toBeLessThan(1e-9);
			}
			const passage = end.approach.length >= 100;
			if (passage && frame === 'interplanetary' && !anchored) {
				const index = end.at === 'departure' ? 0 : arcs.length - 1;
				const { from: kept, to: stop } = crossingWindow(path, index);
				const join = end.at === 'departure' ? kept : stop - 1;
				const seam = end.at === 'departure' ? end.approach.at(-1)! : end.approach[0];
				expect(norm(sub(seam, arcs[index].points[join])), name).toBeLessThan(1);
			}
		}

		// The craft is somewhere on every date of the trip.
		for (let i = 0; i <= 40; i++) {
			const jd = route.departJd + (route.tofDays * i) / 40;
			const at = craftPositionAt(path, jd);
			expect(at, name).not.toBeNull();
			expect(Number.isFinite(norm(at!.r)), name).toBe(true);
		}
	}

	const LEAVING: [string, SystemEnd, Terms][] = [
		['the ground of Earth', HOME, { departureMode: 'surface' }],
		['low Earth orbit', HOME, { departureMode: 'orbit' }],
		['an orbit named for its plane', HOME, { departureMode: 'orbit', departureOrbit: STATION }],
		['a custom orbit with a pole', HOME, { departureMode: 'orbit', departureOrbit: MOLNIYA }],
		['the Moon', AT_MOON, { departureMode: 'orbit' }],
		['the Sun, in a hold', SUN_END, { departureMode: 'rendezvous' }],
		['an orbit of the Sun', SUN_END, { departureMode: 'orbit', departureOrbit: RING }],
		['a planet of another star', FAR_PLANET, { departureMode: 'orbit' }],
		['the ground of that planet', FAR_PLANET, { departureMode: 'surface' }],
		['another star, in a hold', FAR, { departureMode: 'rendezvous' }],
		['an orbit of another star', FAR, { departureMode: 'orbit', departureOrbit: RING }]
	];

	const REACHING: [string, SystemEnd, Terms][] = [
		['low orbit of a planet of a star', FAR_PLANET, { arrivalMode: 'low-orbit' }],
		['a custom orbit there', FAR_PLANET, { arrivalMode: 'capture', targetOrbit: MOLNIYA }],
		['its ground', FAR_PLANET, { arrivalMode: 'landing' }],
		['a flyby of it', FAR_PLANET, { arrivalMode: 'flyby' }],
		['its air', FAR_PLANET, { arrivalMode: 'low-orbit', aero: 'aerocapture' }],
		['a star, to hold', FAR, { arrivalMode: 'rendezvous' }],
		['an orbit of the star', FAR, { arrivalMode: 'capture', targetOrbit: RING }],
		['a flyby of the star', FAR, { arrivalMode: 'flyby' }],
		['low orbit of Mars', AT_MARS, { arrivalMode: 'low-orbit' }],
		['a named orbit of Mars', AT_MARS, { arrivalMode: 'capture', targetOrbit: STATION }],
		['the ground of Mars', AT_MARS, { arrivalMode: 'landing' }],
		['the air of Mars', AT_MARS, { arrivalMode: 'low-orbit', aero: 'aerocapture' }],
		['the Moon', AT_MOON, { arrivalMode: 'low-orbit' }],
		['the Sun, to hold', SUN_END, { arrivalMode: 'rendezvous' }],
		['an orbit of the Sun', SUN_END, { arrivalMode: 'capture', targetOrbit: RING }]
	];

	describe.each(DRIVES)('on a %s', (drive) => {
		it.each(FRAMES)('joins every kind of end in the %s frame', (frame) => {
			let flown = 0;
			for (const [fromName, from, leaving] of LEAVING) {
				for (const [toName, to, reaching] of REACHING) {
					if (inSameSystem(from, to)) continue;
					const name = `${fromName} → ${toName}`;
					const route = fly(drive, from, to, { ...leaving, ...reaching });
					if (route === null || typeof route === 'string') continue;
					flown++;
					expectWhole(draw(from, to, route, { frame }), route, from, to, name);
				}
			}
			expect(flown).toBe(84);
		});
	});

	it('leaves Earth and reaches a planet of another star, each on its own date', () => {
		const terms: Terms = { departureMode: 'orbit', arrivalMode: 'low-orbit' };
		for (const drive of DRIVES) {
			const route = trip(drive, HOME, FAR_PLANET, terms);
			const path = draw(HOME, FAR_PLANET, route);
			expectAtEnd(path.arcs[0].points[0], HOME, route.departJd, null, drive);
			expectAtEnd(path.arcs.at(-1)!.points.at(-1)!, FAR_PLANET, route.arriveJd, null, drive);
			expect(path.soiKm[EARTH.id]).toBeCloseTo(soiOf(EARTH, GM_SUN_KM3_S2), 3);
			expect(path.soiKm[FAR_PLANET.body.id]).toBeGreaterThan(0);
			expect(path.endOrbits.map((end) => end.at)).toEqual(['departure', 'arrival']);
		}
	});

	it('draws the ring that was priced, about the body', () => {
		const route = trip('coast', HOME, FAR_PLANET, {
			departureMode: 'orbit',
			departureOrbit: MOLNIYA,
			arrivalMode: 'low-orbit'
		});
		const path = draw(HOME, FAR_PLANET, route, { frame: 'planetary' });
		const ring = endAt(path, 'departure')!;
		const radii = ring.points.map(norm);
		expect(Math.min(...radii)).toBeCloseTo(MOLNIYA.rPeriKm, 3);
		expect(Math.max(...radii)).toBeCloseTo(MOLNIYA.rApoKm, 3);
		expect(ring.radiusKm).toBe(MOLNIYA.rApoKm);
		const low = parkingOrbit(FAR_PLANET.body).rPeriKm;
		for (const point of endAt(path, 'arrival')!.points) expect(norm(point)).toBeCloseTo(low, 3);
	});

	it('hands a passage down to the periapsis of the orbit', () => {
		const route = trip('coast', HOME, FAR_PLANET, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		});
		const path = draw(HOME, FAR_PLANET, route, { frame: 'planetary' });
		const arrival = endAt(path, 'arrival')!;
		const low = parkingOrbit(FAR_PLANET.body).rPeriKm;
		expect(norm(arrival.approach.at(-1)!)).toBeCloseTo(low, 3);
		expect(relative(arrival.approach.at(-1)!, arrival.points[0])).toBeLessThan(1e-6);
		// The speed there is the one the route was priced on.
		const steps = arrival.approach.length;
		const stepKm = norm(sub(arrival.approach[steps - 1], arrival.approach[steps - 2]));
		const stepSec = (arrival.jds[steps - 1] - arrival.jds[steps - 2]) * SEC_PER_DAY;
		const speed = Math.sqrt(route.vInfArrKms ** 2 + (2 * FAR_PLANET.body.mu) / low);
		expect(stepKm / stepSec / speed).toBeCloseTo(1, 2);
	});

	it('draws the conics of the route, and the closing speed it was priced on', () => {
		const route = trip('coast', HOME, FAR_PLANET, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		});
		const shape = coastShape(route, HOME, FAR_PLANET)!;
		const path = draw(HOME, FAR_PLANET, route);
		expect(path.arcs).toHaveLength(3);
		const [out, line, back] = path.arcs;
		const conicTolerance = 1e-9;
		out.points.forEach((point, i) => {
			const seconds = (out.jds[i] - route.departJd) * SEC_PER_DAY;
			expect(relative(point, conicPlaceKm(shape.departure!, seconds))).toBeLessThan(1e-6);
		});
		back.points.forEach((point, i) => {
			const seconds = (route.arriveJd - back.jds[i]) * SEC_PER_DAY;
			const at = sub(conicPlaceKm(shape.arrival!, seconds), shape.arrival!.starKm);
			expect(norm(sub(sub(point, shape.arrival!.starKm), at)) / norm(at)).toBeLessThan(1e-6);
		});
		expect(relative(line.points[0], shape.lineFromKm)).toBeLessThan(conicTolerance);
		expect(relative(line.points.at(-1)!, shape.lineToKm)).toBeLessThan(conicTolerance);
		expect(out.endJd).toBeCloseTo(route.departJd + shape.departure!.seconds / SEC_PER_DAY, 6);
		expect(back.startJd).toBeCloseTo(route.arriveJd - shape.arrival!.seconds / SEC_PER_DAY, 6);

		// The line runs at the cruise speed.
		const lineSeconds = (line.endJd - line.startJd) * SEC_PER_DAY;
		const lineKm = norm(sub(line.points.at(-1)!, line.points[0]));
		expect(lineKm / lineSeconds / route.interstellar!.cruiseKms).toBeCloseTo(1, 6);

		const met = orbitStateAt(FAR_PLANET, route.arriveJd)!;
		const closing = norm(sub(scale(shape.arrival!.v, -1), met.v));
		expect(closing).toBeCloseTo(rapidityOfSpeed(route.vInfArrKms), 3);
	});

	it('samples a hyperbola by anomaly, so a slow bend is smooth', () => {
		const route = buildInterstellarCruiseRoute(
			SUN_END,
			FAR,
			J2000,
			{ kind: 'budget', dvKms: 30 },
			{ departureMode: 'orbit', departureOrbit: RING }
		) as Route;
		const out = draw(SUN_END, FAR, route).arcs[0];
		const shape = coastShape(route, SUN_END, FAR)!.departure!;
		// It really bends, by more than 15°.
		const turned = dot(normalize(shape.v), normalize(sub(shape.joinKm, shape.starKm)));
		expect(turned).toBeLessThan(Math.cos((15 * Math.PI) / 180));
		const turns = out.points.slice(2).map((point, i) => {
			const one = normalize(sub(out.points[i + 1], out.points[i]));
			const two = normalize(sub(point, out.points[i + 1]));
			return Math.acos(Math.min(1, dot(one, two)));
		});
		expect(Math.max(...turns)).toBeLessThan(0.05);
		// The straight part keeps samples too, out to the join.
		const radii = out.points.map(norm);
		expect(radii[radii.length - 2] / radii[radii.length - 1]).toBeGreaterThan(0.1);
	});

	it('ends a coast at a star on the conic, not on the star', () => {
		const hold = trip('coast', HOME, FAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
		const path = draw(HOME, FAR, hold);
		const held = path.arcs.at(-1)!.points.at(-1)!;
		expectAtEnd(held, FAR, hold.arriveJd, AU_KM, 'hold');
		expect(path.meeting.r).toEqual(held);
		expect(path.meeting.jd).toBe(hold.arriveJd);
		expect(endAt(path, 'arrival')).toBeUndefined();

		const away = trip('coast', FAR, HOME, { departureMode: 'rendezvous', arrivalMode: 'flyby' });
		expectAtEnd(draw(FAR, HOME, away).arcs[0].points[0], FAR, away.departJd, AU_KM, 'away');
	});

	it('lays an orbit at a star in the plane of its conic', () => {
		const route = trip('coast', HOME, FAR, {
			departureMode: 'orbit',
			arrivalMode: 'capture',
			targetOrbit: RING
		});
		for (const frame of FRAMES) {
			const path = draw(HOME, FAR, route, { frame });
			const conic = coastShape(route, HOME, FAR)!.arrival!;
			const ring = endAt(path, 'arrival')!;
			const about = frame === 'planetary' ? ORIGIN : FAR.starKm;
			const normal = normalize(cross(conic.r, conic.v));
			const flat = ring.points.map((point) => sub(point, about));
			for (const point of flat) expect(Math.abs(dot(point, normal)) / AU_KM).toBeLessThan(1e-6);
			// Its low point is the end of the conic, and the craft goes on the way it came.
			expect(norm(sub(flat[0], conic.r)) / AU_KM).toBeLessThan(1e-6);
			const onward = sub(flat[1], flat[0]);
			expect(dot(onward, scale(conic.v, -1))).toBeGreaterThan(0);
			expect(ring.approach).toEqual([]);
			expect(ring.trimTo).toBe(path.arcs.at(-1)!.points.length);
			expect(ring.periJd).toBe(route.arriveJd);
			expect(ring.center).toEqual(FAR.starKm);
		}
	});

	it('honours a plane named at the Sun, which has a pole', () => {
		const sun = {
			...SUN_END,
			body: { ...SUN_END.body, poleEcliptic: [0.1, 0.2, 0.97] as Vec3 }
		};
		const orbit = { ...RING, incDeg: 40 };
		const route = trip('coast', FAR, sun, { arrivalMode: 'capture', targetOrbit: orbit });
		const ring = endAt(draw(FAR, sun, route, { frame: 'planetary' }), 'arrival')!;
		const normal = normalize(cross(ring.points[10], ring.points[30]));
		const lean = (Math.acos(dot(normal, normalize(sun.body.poleEcliptic))) * 180) / Math.PI;
		expect(Math.min(lean, 180 - lean)).toBeCloseTo(40, 3);
		expect(ring.turn).toBeDefined();
		expect(ring.turnJd).toBeGreaterThan(route.arriveJd);
	});

	it('stops a held drive at the orbit, not at the centre', () => {
		for (const [to, terms] of [
			[FAR, { arrivalMode: 'capture', targetOrbit: RING }],
			[FAR_PLANET, { arrivalMode: 'low-orbit' }]
		] as [SystemEnd, Terms][]) {
			const route = trip('held', HOME, to, { departureMode: 'orbit', ...terms });
			const path = draw(HOME, to, route);
			const end = endAt(path, 'arrival')!;
			const last = path.arcs.at(-1)!;
			const rKm = route.targetOrbit?.rPeriKm ?? parkingOrbit(to.body).rPeriKm;
			if (!to.atStar) expect(end.trimTo).toBeLessThan(last.points.length);
			const place = endPlaceKm(to, route.arriveJd);
			expect(norm(sub(last.points[end.trimTo - 1], place)) / rKm).toBeCloseTo(1, 4);
		}
	});

	it('climbs out under thrust and joins the line', () => {
		const route = trip('held', HOME, FAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
		const path = draw(HOME, FAR, route);
		const end = endAt(path, 'departure')!;
		expect(end.trimFrom).toBeGreaterThan(0);
		expect(norm(sub(end.approach.at(-1)!, path.arcs[0].points[end.trimFrom]))).toBeLessThan(1e-3);
		// Earth's own sphere of influence bounds the climb.
		const reach = norm(sub(end.approach.at(-1)!, end.center));
		expect(reach / soiOf(EARTH, GM_SUN_KM3_S2)).toBeGreaterThan(0.5);
		expect(reach / soiOf(EARTH, GM_SUN_KM3_S2)).toBeLessThan(1.5);
	});

	it('finds the middle of a stretch whose samples crowd toward an end', () => {
		const route = trip('held', HOME, FAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
		const path = draw(HOME, FAR, route);
		const [boost] = path.arcs;
		const view = pathViewpoint(path, boost.startJd, boost.endJd)!;
		const half = norm(sub(boost.points.at(-1)!, boost.points[0])) / 2;
		expect(norm(sub(view.r, boost.points[0])) / half).toBeCloseTo(1, 6);
	});

	it('turns a named plane at a node of the passage', () => {
		const route = trip('coast', HOME, FAR, {
			departureMode: 'orbit',
			departureOrbit: STATION,
			arrivalMode: 'rendezvous'
		});
		const end = endAt(draw(HOME, FAR, route, { frame: 'planetary' }), 'departure')!;
		const normal = normalize(cross(end.points[10], end.points[30]));
		const lean = (Math.acos(dot(normal, normalize(EARTH.poleEcliptic!))) * 180) / Math.PI;
		expect(Math.min(lean, 180 - lean)).toBeCloseTo(STATION.incDeg, 3);
		expect(end.turn).toBeDefined();
	});

	it('flies an aerocapture down through the air of a far planet', () => {
		const route = trip('coast', HOME, FAR_PLANET, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit',
			aero: 'aerocapture'
		});
		expect(route.legs.some((leg) => leg.aerobraked)).toBe(true);
		const end = endAt(draw(HOME, FAR_PLANET, route, { frame: 'planetary' }), 'arrival')!;
		const lowest = Math.min(...end.approach.map(norm));
		expect(lowest).toBeCloseTo(aeroPassRadiusKm(FAR_PLANET.body), 3);
		expect(end.ground?.length).toBeGreaterThan(0);
	});

	it('lands on the site of a far planet and lifts off from one at home', () => {
		const site = (jd: number): Vec3 => [6_300 * Math.cos(jd), 6_300 * Math.sin(jd), 1_000];
		for (const drive of DRIVES) {
			const route = trip(drive, HOME, FAR_PLANET, {
				departureMode: 'surface',
				arrivalMode: 'landing'
			});
			const path = draw(HOME, FAR_PLANET, route, {
				frame: 'planetary',
				surfaceSites: { departure: site, arrival: site }
			});
			const [leaving, reaching] = path.endOrbits;
			expect(relative(leaving.approach[0], site(leaving.surfaceJd!))).toBeLessThan(1e-9);
			expect(relative(reaching.approach.at(-1)!, site(reaching.surfaceJd!))).toBeLessThan(1e-9);
			expect(leaving.surfaceJd).toBeLessThan(route.departJd);
			expect(reaching.surfaceJd).toBeGreaterThan(path.meeting.jd);
		}
	});

	it('flies by with no end orbit', () => {
		for (const drive of DRIVES) {
			const route = trip(drive, HOME, FAR_PLANET, {
				departureMode: 'orbit',
				arrivalMode: 'flyby'
			});
			const path = draw(HOME, FAR_PLANET, route);
			expect(path.endOrbits.map((end) => end.at)).toEqual(['departure']);
			expectAtEnd(path.arcs.at(-1)!.points.at(-1)!, FAR_PLANET, route.arriveJd, null, drive);
		}
	});

	it('draws a solar moon off its live body, on the elements it borrows', () => {
		const route = trip('coast', AT_MOON, FAR, {
			departureMode: 'orbit',
			arrivalMode: 'rendezvous'
		});
		const path = draw(AT_MOON, FAR, route);
		const end = endAt(path, 'departure')!;
		expect(end.anchorId).toBe(MOON.id);
		// The priced centre stays the planet's place.
		expect(relative(end.center, endPlaceKm(AT_MOON, route.departJd))).toBeLessThan(1e-12);
		const low = parkingOrbit(AT_MOON.body).rPeriKm;
		expect(norm(end.approach[0])).toBeCloseTo(low, 3);
	});

	it('leaves the Sun from a conic and arrives at it on one', () => {
		for (const [from, to, terms] of [
			[SUN_END, FAR, { departureMode: 'orbit', departureOrbit: RING }],
			[FAR, SUN_END, { arrivalMode: 'capture', targetOrbit: RING }]
		] as [SystemEnd, SystemEnd, Terms][]) {
			const route = trip('coast', from, to, terms);
			const path = draw(from, to, route);
			const end = path.endOrbits.find((orbit) => orbit.bodyId === SUN)!;
			expect(end.points.length).toBeGreaterThan(2);
			const inner = from === SUN_END ? path.arcs[0].points[0] : path.arcs.at(-1)!.points.at(-1)!;
			expect(norm(inner) / RING.rPeriKm).toBeCloseTo(1, 6);
		}
	});

	describe('a held drive at a star with no orbit', () => {
		const HOLD = { departureMode: 'rendezvous', arrivalMode: 'rendezvous' } as const;

		it('starts 1 au from the Sun on the line, and the first stop is there', () => {
			const route = trip('held', SUN_END, FAR, HOLD);
			const path = draw(SUN_END, FAR, route);
			const start = path.arcs[0].points[0];
			expect(norm(start)).toBeCloseTo(AU_KM, 3);
			expect(norm(cross(normalize(start), normalize(FAR.starKm)))).toBeLessThan(1e-12);
			expect(dot(start, FAR.starKm)).toBeGreaterThan(0);
			expect(start).toEqual(heldLine(SUN_END, FAR, route).originKm);
			expect(path.stops[0].r).toEqual(start);
			expect(path.endOrbits).toEqual([]);
		});

		it.each(['rendezvous', 'flyby'] as const)(
			'stops 1 au short of a star on a %s',
			(arrivalMode) => {
				const route = trip('held', HOME, FAR, { departureMode: 'orbit', arrivalMode });
				const path = draw(HOME, FAR, route);
				const end = path.arcs.at(-1)!.points.at(-1)!;
				expect(norm(sub(end, FAR.starKm)) / AU_KM).toBeCloseTo(1, 6);
				expect(end).toEqual(heldLine(HOME, FAR, route).targetKm);
				expect(path.stops[1].r).toEqual(end);
				expect(path.meeting.r).toEqual(end);
				expect(endAt(path, 'arrival')).toBeUndefined();
			}
		);

		it.each(['rendezvous', 'flyby'] as const)(
			'stops 2 radii short of a giant on a %s',
			(arrivalMode) => {
				const giant = { ...FAR, body: { ...FAR.body, radiusKm: 8 * AU_KM } };
				const route = trip('held', HOME, giant, { departureMode: 'orbit', arrivalMode });
				const path = draw(HOME, giant, route);
				const end = path.arcs.at(-1)!.points.at(-1)!;
				expect(norm(sub(end, giant.starKm)) / AU_KM).toBeCloseTo(16, 6);
				expect(path.meeting.r).toEqual(end);
			}
		);

		it('starts 2 radii out from a giant', () => {
			const giant = { ...FAR, body: { ...FAR.body, radiusKm: 8 * AU_KM } };
			const route = trip('held', giant, HOME, {
				departureMode: 'rendezvous',
				arrivalMode: 'flyby'
			});
			const start = draw(giant, HOME, route).arcs[0].points[0];
			expect(norm(sub(start, giant.starKm)) / AU_KM).toBeCloseTo(16, 6);
		});

		it('adds the offset of the Sun to the place it stands off from', () => {
			const offset: Vec3 = [1e6, -2e6, 3e5];
			const route = trip('held', SUN_END, FAR, HOLD);
			const plain = draw(SUN_END, FAR, route);
			const moved = draw(SUN_END, FAR, route, { sunOffsetKm: () => offset });
			expect(norm(sub(moved.arcs[0].points[0], add(plain.arcs[0].points[0], offset)))).toBeLessThan(
				1e-6
			);
		});

		it('keeps every digit of the stand-off at a far star', () => {
			const star = starEnd('x-9', [8e15, 5e15, -3e15]);
			const route = trip('held', HOME, star, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
			const path = draw(HOME, star, route, { centerId: star.body.id, centerKm: star.starKm });
			expect(Math.abs(norm(path.meeting.r) - AU_KM)).toBeLessThan(1e-6);
		});

		it('keeps the two ends of a close binary apart and in order', () => {
			const near = starEnd('x-7', add(ALPHA.starKm, [0.1 * AU_KM, 0, 0]), 0.9);
			const route = trip('held', ALPHA, near, HOLD);
			const path = draw(ALPHA, near, route, { centerId: ALPHA.body.id, centerKm: ALPHA.starKm });
			const xs = path.arcs.flatMap((arc) => arc.points.map((point) => point[0] / AU_KM));
			expect(xs[0]).toBeCloseTo(0.025, 6);
			expect(xs.at(-1)).toBeCloseTo(0.075, 6);
			for (let i = 1; i < xs.length; i++) expect(xs[i]).toBeGreaterThanOrEqual(xs[i - 1]);
		});
	});

	it('flies between both stars of a binary, and between their planets', () => {
		const alpha = planetOf(ALPHA, 'b', 1);
		const beta = planetOf(BETA, 'c', 1.5);
		for (const drive of DRIVES) {
			for (const [from, to] of [
				[ALPHA, BETA],
				[alpha, beta],
				[alpha, BETA]
			]) {
				const terms: Terms = {
					departureMode: from.atStar ? 'rendezvous' : 'orbit',
					arrivalMode: to.atStar ? 'rendezvous' : 'low-orbit'
				};
				const route = trip(drive, from, to, terms);
				const path = draw(from, to, route, { centerId: ALPHA.body.id, centerKm: ALPHA.starKm });
				const about = { ...from, starKm: sub(from.starKm, ALPHA.starKm) };
				expectAtEnd(
					path.arcs[0].points[0],
					about,
					route.departJd,
					from.atStar ? AU_KM : null,
					drive
				);
				// The line keeps a place between the two wells.
				if (drive === 'coast') {
					expect(
						norm(sub(path.arcs[1].points.at(-1)!, path.arcs[1].points[0])) / AU_KM
					).toBeGreaterThan(5);
				}
			}
		}
	});

	it('runs the line to the place where a conic has no room', () => {
		// An orbit of 10 au about a star with a neighbour at 23 au fills the room.
		const wide = planetOf(ALPHA, 'd', 10);
		const route = trip('coast', wide, BETA, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
		expect(coastShape(route, wide, BETA)!.departure!.seconds).toBe(0);
		const path = draw(wide, BETA, route, { centerId: ALPHA.body.id, centerKm: ALPHA.starKm });
		expect(path.arcs).toHaveLength(2);
		const about = { ...wide, starKm: ORIGIN };
		expectAtEnd(path.arcs[0].points[0], about, route.departJd, null, 'start');
		expectWhole(path, route, about, { ...BETA, starKm: sub(BETA.starKm, ALPHA.starKm) }, 'room');
	});

	it.each(['rendezvous', 'flyby'] as const)(
		'stands a coast off a star with no μ on a %s',
		(arrivalMode) => {
			const unknown: SystemEnd = { ...FAR, body: { ...FAR.body, mu: 0 }, starMu: undefined };
			const route = trip('coast', HOME, unknown, { departureMode: 'orbit', arrivalMode });
			expect(coastShape(route, HOME, unknown)!.arrival).toBeNull();
			const path = draw(HOME, unknown, route);
			expect(path.arcs).toHaveLength(2);
			const end = path.arcs.at(-1)!.points.at(-1)!;
			expect(norm(sub(end, unknown.starKm)) / AU_KM).toBeCloseTo(1, 6);
			expect(dot(sub(end, unknown.starKm), sub(HOME.starKm, unknown.starKm))).toBeGreaterThan(0);
			expect(path.meeting.r).toEqual(end);
			expect(path.arcs.at(-1)!.endJd).toBe(route.arriveJd);
			expect(route.interstellar!.conics!.arrival.km / AU_KM).toBeCloseTo(1, 6);
			expect(route.interstellar!.conics!.arrival.days).toBe(0);
		}
	);

	it.each(['rendezvous', 'flyby'] as const)(
		'stands a coast off a giant with no μ by 2 radii on a %s',
		(arrivalMode) => {
			const giant: SystemEnd = {
				...FAR,
				body: { ...FAR.body, mu: 0, radiusKm: 8 * AU_KM },
				starMu: undefined
			};
			const route = trip('coast', HOME, giant, { departureMode: 'orbit', arrivalMode });
			const end = draw(HOME, giant, route).arcs.at(-1)!.points.at(-1)!;
			expect(norm(sub(end, giant.starKm)) / AU_KM).toBeCloseTo(16, 6);
			expect(route.interstellar!.conics!.arrival.km / AU_KM).toBeCloseTo(16, 6);
		}
	);

	it('stands a coast off a star with no μ at the start, less in a close binary', () => {
		const unknown: SystemEnd = { ...ALPHA, body: { ...ALPHA.body, mu: 0 }, starMu: undefined };
		const near = starEnd('x-8', add(ALPHA.starKm, [2 * AU_KM, 0, 0]), 0.9);
		const route = trip('coast', unknown, near, {
			departureMode: 'rendezvous',
			arrivalMode: 'rendezvous'
		});
		const path = draw(unknown, near, route, { centerId: ALPHA.body.id, centerKm: ALPHA.starKm });
		expect(path.arcs[0].points[0][0] / AU_KM).toBeCloseTo(0.5, 6);
		expect(path.arcs[0].startJd).toBe(route.departJd);
	});

	describe('a held line and a ring wider than a stretch', () => {
		const WIDE = { rPeriKm: 20 * AU_KM, rApoKm: 20 * AU_KM };
		const LOCAL = { centerId: ALPHA.body.id, centerKm: ALPHA.starKm };
		const reaching = { departureMode: 'rendezvous', arrivalMode: 'low-orbit' } as const;
		const leaving = { departureMode: 'orbit', arrivalMode: 'rendezvous' } as const;

		/** The drawn line, km about ALPHA along x, in flight order. */
		function line(path: Path): number[] {
			return path.arcs.flatMap((arc, index) => {
				const { from, to } = crossingWindow(path, index);
				return arc.points.slice(from, to).map((point) => point[0] / AU_KM);
			});
		}

		it('stops the line at the ring of the target', () => {
			const route = trip('held', ALPHA, BETA, { ...reaching, targetOrbit: WIDE });
			const path = draw(ALPHA, BETA, route, LOCAL);
			expect(route.legs.map((leg) => leg.kind)).toContain('brake');
			expect(path.arcs).toHaveLength(1);
			const xs = line(path);
			expect(xs[0]).toBeCloseTo(1, 6);
			expect(xs.at(-1)).toBeCloseTo(3, 4);
			expect(Math.max(...xs)).toBeLessThan(3.001);
			expect(path.arcs.at(-1)!.endJd).toBe(route.arriveJd);
			expect(endAt(path, 'arrival')!.points.length).toBeGreaterThan(0);
		});

		it('starts the line at the ring of the origin', () => {
			const route = trip('held', ALPHA, BETA, { ...leaving, departureOrbit: WIDE });
			const path = draw(ALPHA, BETA, route, LOCAL);
			expect(path.arcs).toHaveLength(1);
			const xs = line(path);
			expect(xs[0]).toBeCloseTo(20, 4);
			expect(Math.min(...xs)).toBeGreaterThan(19.999);
			expect(xs.at(-1)).toBeCloseTo(22, 6);
			expect(path.arcs[0].startJd).toBe(route.departJd);
		});

		it('keeps a craft on the drawn line, in date order', () => {
			const route = trip('held', ALPHA, BETA, { ...reaching, targetOrbit: WIDE });
			const path = draw(ALPHA, BETA, route, LOCAL);
			const { jds } = path.arcs[0];
			for (let i = 1; i < jds.length; i++) expect(jds[i]).toBeGreaterThan(jds[i - 1]);
			const middle = (route.departJd + route.arriveJd) / 2;
			expect(craftPositionAt(path, middle)!.r[0] / AU_KM).toBeLessThan(3.001);
		});

		it('leaves a stretch that the ring does not reach', () => {
			const route = trip('held', ALPHA, BETA, {
				...reaching,
				targetOrbit: { rPeriKm: 12 * AU_KM, rApoKm: 12 * AU_KM }
			});
			const path = draw(ALPHA, BETA, route, LOCAL);
			expect(path.arcs).toHaveLength(1);
			expect(line(path).at(-1)).toBeCloseTo(11, 4);
		});

		it.each([
			['a ring wider than the whole line', { departureMode: 'rendezvous' }, 30, null],
			['two rings that overlap', { departureMode: 'orbit' }, 15, 15]
		] as const)('keeps a line and no centre with %s', (_name, modes, toAu, fromAu) => {
			const route = trip('held', ALPHA, BETA, {
				...modes,
				arrivalMode: 'low-orbit',
				targetOrbit: { rPeriKm: toAu * AU_KM, rApoKm: toAu * AU_KM },
				departureOrbit: fromAu ? { rPeriKm: fromAu * AU_KM, rApoKm: fromAu * AU_KM } : undefined
			});
			const path = draw(ALPHA, BETA, route, LOCAL);
			const xs = line(path);
			expect(xs.length).toBeGreaterThan(1);
			expect(Math.min(...xs)).toBeGreaterThan(0.5);
			expect(Math.max(...xs)).toBeLessThan(22.5);
			expect(path.arcs[0].startJd).toBe(route.departJd);
			expect(path.arcs.at(-1)!.endJd).toBe(route.arriveJd);
		});

		it('stops at a narrow ring as well, so that an offer stops there too', () => {
			const route = trip('held', ALPHA, BETA, { ...reaching, targetOrbit: RING });
			const path = draw(ALPHA, BETA, route, LOCAL);
			expect(path.arcs).toHaveLength(2);
			expect(path.arcs.at(-1)!.points.at(-1)![0] / AU_KM).toBeCloseTo(21, 4);
			expect(endAt(path, 'arrival')!.trimTo).toBe(path.arcs.at(-1)!.points.length);
		});

		it('keeps the passage from a ring at a star, on a line that starts at the ring', () => {
			const route = trip('held', SUN_END, FAR, {
				departureMode: 'orbit',
				arrivalMode: 'rendezvous',
				departureOrbit: RING
			});
			const path = draw(SUN_END, FAR, route);
			expect(norm(path.arcs[0].points[0]) / RING.rPeriKm).toBeCloseTo(1, 4);
			expect(endAt(path, 'departure')!.approach.length).toBeGreaterThan(1);
			expect(path.arcs[0].startJd).toBe(route.departJd);
		});
	});

	it.each(DRIVES)('reaches no centre of a star on any arc of a %s', (drive) => {
		const TERMS: Terms[] = [
			{ arrivalMode: 'rendezvous' },
			{ arrivalMode: 'flyby' },
			{ arrivalMode: 'low-orbit', targetOrbit: RING }
		];
		for (const terms of TERMS) {
			const route = trip(drive, HOME, FAR, { departureMode: 'orbit', ...terms });
			const points = draw(HOME, FAR, route).arcs.flatMap((arc) => arc.points);
			const nearest = Math.min(...points.map((point) => norm(sub(point, FAR.starKm))));
			expect(nearest / AU_KM).toBeGreaterThan(0.9);
		}
	});

	it('keeps a line between two passages that would meet', () => {
		// Two planets of unknown stars have no conics, so one arc meets both ends, and
		// no μ of a star bounds their passages. Each reaches past the middle of it.
		const still = (id: string, km: Vec3): SystemEnd => {
			const { body } = planetOf(FAR, id, 1);
			const elements = { ...body.elements, a: 0, n: 0 };
			return {
				body: { ...body, radiusKm: 2_500, elements },
				starKm: km,
				atStar: false
			};
		};
		const from = still('near', [LIGHT_YEAR_KM, 0, 0]);
		const to = still('far', [LIGHT_YEAR_KM + 1e6, 0, 0]);
		const route = trip('coast', from, to, { departureMode: 'orbit', arrivalMode: 'low-orbit' });
		const path = draw(from, to, route);
		expect(path.arcs).toHaveLength(1);
		expect(path.endOrbits.map((end) => end.approach.length)).toEqual([160, 160]);
		const { from: kept, to: stop } = crossingWindow(path, 0);
		expect(stop - kept).toBe(path.arcs[0].points.length);
	});

	describe("the Sun's offset", () => {
		const OFFSET = (jd: number): Vec3 => [1e6, -2e6, 3e5 + (jd - J2000)];

		it('moves a coast at the solar end only, by its value at that date', () => {
			const route = trip('coast', HOME, FAR_PLANET, {
				departureMode: 'orbit',
				arrivalMode: 'low-orbit'
			});
			const plain = draw(HOME, FAR_PLANET, route);
			const dates: number[] = [];
			const moved = draw(HOME, FAR_PLANET, route, {
				sunOffsetKm: (jd) => {
					dates.push(jd);
					return OFFSET(jd);
				}
			});
			expect(dates).toEqual([route.departJd]);
			const offset = OFFSET(route.departJd);
			plain.arcs[0].points.forEach((point, i) => {
				expect(norm(sub(moved.arcs[0].points[i], add(point, offset)))).toBeLessThan(1e-6);
			});
			const [plainLine, movedLine] = [plain.arcs[1], moved.arcs[1]];
			expect(norm(sub(movedLine.points[0], add(plainLine.points[0], offset)))).toBeLessThan(1e-6);
			expect(movedLine.points.at(-1)).toEqual(plainLine.points.at(-1));
			expect(moved.arcs.at(-1)!.points).toEqual(plain.arcs.at(-1)!.points);
			expect(moved.meeting.r).toEqual(plain.meeting.r);

			// The ends of the trip keep the body they were drawn on.
			const end = endAt(moved, 'departure')!;
			expect(norm(sub(end.center, add(endAt(plain, 'departure')!.center, offset)))).toBeLessThan(
				1e-6
			);
			expect(norm(sub(end.approach.at(-1)!, moved.arcs[0].points[end.trimFrom]))).toBeLessThan(0.1);
		});

		it('moves a trip to the Sun at its arrival date', () => {
			const route = trip('coast', FAR, HOME, {
				departureMode: 'rendezvous',
				arrivalMode: 'low-orbit'
			});
			const plain = draw(FAR, HOME, route);
			const moved = draw(FAR, HOME, route, { sunOffsetKm: OFFSET });
			expect(moved.arcs[0].points).toEqual(plain.arcs[0].points);
			const offset = OFFSET(route.arriveJd);
			expect(
				norm(sub(moved.arcs.at(-1)!.points.at(-1)!, add(plain.arcs.at(-1)!.points.at(-1)!, offset)))
			).toBeLessThan(1e-6);
		});

		it('moves only the solar end point of a held arc', () => {
			const route = trip('held', HOME, FAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
			const plain = draw(HOME, FAR, route);
			const moved = draw(HOME, FAR, route, { sunOffsetKm: OFFSET });
			const offset = OFFSET(route.departJd);
			expect(norm(sub(moved.arcs[0].points[0], add(plain.arcs[0].points[0], offset)))).toBeLessThan(
				1e-6
			);
			expect(moved.arcs.at(-1)!.points.at(-1)).toEqual(heldLine(HOME, FAR, route).targetKm);
			const middle = norm(sub(moved.arcs[0].points.at(-1)!, plain.arcs[0].points.at(-1)!));
			expect(middle / norm(offset)).toBeCloseTo(0.5, 3);
		});

		it('moves nothing without a value, or between two other stars', () => {
			const route = trip('coast', HOME, FAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
			expect(draw(HOME, FAR, route, { sunOffsetKm: () => null }).arcs).toEqual(
				draw(HOME, FAR, route).arcs
			);
			const between = trip('held', ALPHA, FAR, { arrivalMode: 'rendezvous' });
			const called = draw(ALPHA, FAR, between, {
				sunOffsetKm: () => {
					throw new Error('read at a trip that does not touch the Sun');
				}
			});
			expect(called.arcs[0].points[0]).toEqual(heldLine(ALPHA, FAR, between).originKm);
		});
	});

	it('keeps its digits at a far end', () => {
		const star = starEnd('x-9', [8e15, 5e15, -3e15]);
		const planet = planetOf(star, 'b', 1);
		const route = trip('held', HOME, planet, { departureMode: 'orbit', arrivalMode: 'low-orbit' });
		const low = parkingOrbit(planet.body).rPeriKm;

		// Planet-frame, the ring is measured off the body and has every digit.
		const near = endAt(draw(HOME, planet, route, { frame: 'planetary' }), 'arrival')!;
		for (const point of near.points) expect(Math.abs(norm(point) - low)).toBeLessThan(1e-8);

		// Interplanetary, it takes one rounding, of the size of a double out there.
		const far = endAt(draw(HOME, planet, route), 'arrival')!;
		for (const point of far.points) {
			expect(Math.abs(norm(sub(point, far.center)) - low)).toBeLessThan(5);
		}
	});

	it('hands the viewpoint of a coast to the line, and the craft along all three arcs', () => {
		const route = trip('coast', HOME, FAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
		const path = draw(HOME, FAR, route);
		const view = pathViewpoint(path, route.departJd, route.arriveJd)!;
		const length = norm(sub(path.meeting.r, path.stops[0].r));
		expect(norm(sub(view.r, path.stops[0].r)) / length).toBeCloseTo(0.5, 3);
		expect(view.centerId).toBeUndefined();

		for (const arc of path.arcs) {
			const middle = (arc.startJd + arc.endJd) / 2;
			const at = craftPositionAt(path, middle)!.r;
			const span = norm(sub(arc.points.at(-1)!, arc.points[0]));
			expect(Math.min(...arc.points.map((point) => norm(sub(point, at))))).toBeLessThan(span);
		}
	});

	it('has no geometry without its two ends', () => {
		const route = trip('held', HOME, FAR, { departureMode: 'orbit', arrivalMode: 'rendezvous' });
		expect(buildTrajectoryPath(EARTH, FAR.body, route, { centerId: SSB })).toBeNull();
	});
});
