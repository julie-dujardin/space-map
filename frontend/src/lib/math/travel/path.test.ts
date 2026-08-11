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
import { parkingRadiusKm } from './maneuvers';
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

	it('breaks a swing-by into two arcs meeting at the body it passes', () => {
		const route = ASSIST_ROUTE;
		const path = buildTrajectoryPath(EARTH, JUPITER, route, { centerId: SUN, vias: [VENUS] })!;
		expect(path.arcs).toHaveLength(2);
		expect(path.stops.map((s) => s.kind)).toEqual(['departure', 'assist', 'arrival']);

		const first = path.arcs[0].points;
		const second = path.arcs[1].points;
		// The two arcs are the same trajectory, so they share the point they meet at.
		expect(relative(first[first.length - 1], second[0])).toBeLessThan(1e-9);
		expect(relative(path.stops[1].r, second[0])).toBeLessThan(1e-9);
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

	it('has no passage to draw where nothing is flown on a conic', () => {
		// A drive held all the way arrives under braking rather than on a hyperbola,
		// so its ends are the orbit alone.
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path.endOrbits).toHaveLength(2);
		for (const end of path.endOrbits) expect(end.approach).toEqual([]);
	});

	it('draws the loose ellipse a capture leaves the craft in', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'capture' })!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN, frame: 'planetary' })!;
		// A launch from the ground is not an orbit, so only the far end gets a ring.
		expect(path.endOrbits.map((orbit) => orbit.at)).toEqual(['arrival']);
		checkRing(
			path.endOrbits[0],
			parkingRadiusKm(MARS),
			travelConstants.CAPTURE_APOAPSIS_RADII * MARS.radiusKm
		);
	});

	it('has nothing to draw at an end the craft lands on or flies past', () => {
		const landing = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'landing' })!;
		const flyby = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, { arrivalMode: 'flyby' })!;
		for (const route of [landing, flyby]) {
			const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
			expect(path.endOrbits).toEqual([]);
		}
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
		expect(relative(craftPositionAt(PATH, ROUTE.departJd)!.r, PATH.stops[0].r)).toBeLessThan(1e-9);
		// Not on the arrival stop: that is the crossing reaching Mars' centre, a
		// place the craft never goes. It ends at the periapsis the insertion burn is
		// made at, which is where the drawn passage ends too.
		const arrival = PATH.endOrbits.find((end) => end.at === 'arrival')!;
		const last = arrival.approach[arrival.approach.length - 1];
		expect(relative(craftPositionAt(PATH, ROUTE.arriveJd)!.r, last)).toBeLessThan(1e-9);
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

	it('has no craft to place before it leaves or after it lands', () => {
		expect(craftPositionAt(PATH, ROUTE.departJd - 1)).toBeNull();
		expect(craftPositionAt(PATH, ROUTE.arriveJd + 1)).toBeNull();
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
		// Both arcs meet there, so either answer is the same place.
		expect(relative(at, path.arcs[1].points[0])).toBeLessThan(1e-9);
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
		expect(second.r).toEqual(path.arcs[1].points[Math.floor(path.arcs[1].points.length / 2)]);
	});

	it('has nowhere to point on a path with no arcs', () => {
		expect(pathViewpoint({ ...PATH, arcs: [] }, ROUTE.departJd, ROUTE.arriveJd)).toBeNull();
	});
});
