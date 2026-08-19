import { describe, it, expect } from 'vitest';
import {
	buildTrajectoryPath,
	pathViewpoint,
	type EndOrbitPath,
	type TrajectoryFrame
} from './path';
import { craftPositionAt } from './path-sample';
import { buildRoute } from './route';
import { buildAssistRoute } from './assist';
import { buildConstantThrustRoute } from './brachistochrone';
import { elementsToState } from './state';
import { hohmannTransferDays, nextTransferWindows } from './windows';
import { GM_SUN_KM3_S2 } from './constants';
import * as travelConstants from './constants';
import { AU_KM } from '$lib/math/units';
import { sphereOfInfluenceKm } from './body';
import { aeroPassRadiusKm, parkingOrbit, parkingRadiusKm } from './maneuvers';
import { add, cross, dot, norm, normalize, sub, type Vec3 } from './vec3';
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

		const earthAt = elementsToState(EARTH.elements, route.departJd, GM_SUN_KM3_S2)!;
		const marsAt = elementsToState(MARS.elements, route.arriveJd, GM_SUN_KM3_S2)!;
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
		const marsNow = elementsToState(MARS.elements, route.departJd, GM_SUN_KM3_S2)!;

		// The date is the arrival's, corrected by the passage: the craft is at
		// periapsis hours before the crossing would have reached the centre.
		expect(path.meeting.jd).toBeLessThanOrEqual(route.arriveJd);
		expect(path.meeting.jd).toBeGreaterThan(route.arriveJd - 1);
		expect(path.meeting.bodyId).toBe(MARS.id);
		const marsThen = elementsToState(MARS.elements, path.meeting.jd, GM_SUN_KM3_S2)!;
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

		const venusAt = (jd: number) => elementsToState(VENUS.elements, jd, GM_SUN_KM3_S2)!.r;
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
		const from = elementsToState(PARABOLIC_COMET.elements, route.departJd, GM_SUN_KM3_S2)!;
		const to = elementsToState(PARABOLIC_COMET_FAR.elements, route.arriveJd, GM_SUN_KM3_S2)!;
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
		const earthAt = elementsToState(EARTH.elements, route.departJd, GM_SUN_KM3_S2)!;
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
			const state = elementsToState(body.elements, arc.jds[index], GM_SUN_KM3_S2)!;
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
		const mars = elementsToState(MARS.elements, arrival.periJd, GM_SUN_KM3_S2)!;
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
				const here = elementsToState(body.elements, jd, GM_SUN_KM3_S2)!.r;
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
		const venusAt = elementsToState(VENUS.elements, flyby.jd, GM_SUN_KM3_S2)!.r;
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
