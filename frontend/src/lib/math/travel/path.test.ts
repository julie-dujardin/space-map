import { describe, it, expect } from 'vitest';
import { buildTrajectoryPath, pathViewpoint, type EndOrbitPath } from './path';
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
import { cross, dot, norm, normalize, sub, type Vec3 } from './vec3';
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
		const marsThen = elementsToState(MARS.elements, route.arriveJd, GM_SUN_KM3_S2)!;

		expect(path.meeting.jd).toBe(route.arriveJd);
		expect(path.meeting.bodyId).toBe(MARS.id);
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
	/** Every point of `ring` is the distance from its centre a bound orbit between
	 *  the two radii would be, and it closes. */
	function checkRing(ring: EndOrbitPath, rPeriKm: number, rApoKm: number) {
		const radii = ring.points.map((point) => norm(sub(point, ring.center)));
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

	it('rings both ends of a trip flown orbit to orbit', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path.endOrbits.map((orbit) => orbit.at)).toEqual(['departure', 'arrival']);

		const [departure, arrival] = path.endOrbits;
		expect(departure.bodyId).toBe(EARTH.id);
		expect(arrival.bodyId).toBe(MARS.id);
		checkRing(departure, parkingRadiusKm(EARTH), parkingRadiusKm(EARTH));
		checkRing(arrival, parkingRadiusKm(MARS), parkingRadiusKm(MARS));
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
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;

		for (const end of path.endOrbits) {
			const rPeri = parkingRadiusKm(end.at === 'departure' ? EARTH : MARS);
			// The passage runs between the sphere of influence and periapsis, in
			// flight order: out from the burn on the way up, down to it on the way in.
			expect(end.approach.length).toBeGreaterThan(2);
			const periapsis = periapsisOf(end);
			expect(norm(sub(periapsis, end.center))).toBeCloseTo(rPeri, 3);

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

	it('sheds the body\u2019s own motion on the way down, and is the bare conic at periapsis', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;

		for (const end of path.endOrbits) {
			const body = end.at === 'departure' ? EARTH : MARS;
			const radii = end.approach.map((point) => norm(sub(point, end.center)));
			// Nothing of the other frame is left at the low point: it is exactly the
			// periapsis the burn was priced at.
			expect(Math.min(...radii)).toBeCloseTo(parkingRadiusKm(body), 6);
			// And all of it out where the crossing hands over, which is why that end
			// is further out than the sphere of influence rather than on it.
			expect(Math.max(...radii)).toBeGreaterThan(soiOf(body, GM_SUN_KM3_S2));
			// One way down: the passage never turns back on itself.
			for (let i = 1; i < radii.length; i++) {
				const climbing = end.at === 'departure';
				expect(climbing ? radii[i] > radii[i - 1] : radii[i] < radii[i - 1]).toBe(true);
			}
		}
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
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
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
			systemPrimary: 'departure'
		})!;
		const [departure, arrival] = path.endOrbits;
		expect(norm(departure.center)).toBe(0);
		// And the Moon's, out where the Moon is when the craft gets there.
		expect(norm(arrival.center)).toBeGreaterThan(300_000);
		checkRing(arrival, parkingRadiusKm(MOON), parkingRadiusKm(MOON));
	});

	it('lays the orbit in one plane, and lets the passage leave it', () => {
		const route = buildRoute(EARTH, MARS, MARS_WINDOW, MARS_TOF, {
			departureMode: 'orbit',
			arrivalMode: 'low-orbit'
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		for (const end of path.endOrbits) {
			const quarter = end.points[Math.floor(end.points.length / 4)];
			const normal = normalize(cross(sub(end.points[0], end.center), sub(quarter, end.center)));
			// The orbit is a conic and nothing else, out of plane by nothing at
			// whatever distance — measured against each point's own, since an ellipse
			// is a good deal wider in one direction than the other.
			for (const point of end.points) {
				const from = sub(point, end.center);
				expect(Math.abs(dot(from, normal)) / norm(from)).toBeLessThan(1e-9);
			}
			// The passage starts in that plane and works its way out of it, because
			// the body's own motion is not in it. Which is the whole trick, so it is
			// worth pinning: in the plane at the low point, out of it at the far end.
			const outOfPlane = (point: Vec3) => Math.abs(dot(sub(point, end.center), normal));
			const low = end.at === 'departure' ? end.approach[0] : end.approach[end.approach.length - 1];
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

	it('starts on the departure and ends on the arrival', () => {
		expect(relative(craftPositionAt(PATH, ROUTE.departJd)!, PATH.stops[0].r)).toBeLessThan(1e-9);
		expect(relative(craftPositionAt(PATH, ROUTE.arriveJd)!, PATH.stops[1].r)).toBeLessThan(1e-9);
	});

	it('has no craft to place before it leaves or after it lands', () => {
		expect(craftPositionAt(PATH, ROUTE.departJd - 1)).toBeNull();
		expect(craftPositionAt(PATH, ROUTE.arriveJd + 1)).toBeNull();
	});

	it('moves along the arc, and only forwards', () => {
		let previous = craftPositionAt(PATH, ROUTE.departJd)!;
		let travelled = 0;
		for (let i = 1; i <= 40; i++) {
			const at = craftPositionAt(PATH, ROUTE.departJd + (ROUTE.tofDays * i) / 40)!;
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
		const quarter = craftPositionAt(path, route.departJd + route.tofDays / 4)!;
		const alongAtQuarter = norm(sub(quarter, start)) / total;
		expect(alongAtQuarter).toBeGreaterThan(0.05);
		expect(alongAtQuarter).toBeLessThan(0.2);
		// And the flip is still near the middle of the crossing, as the pricing
		// assumes — both burns are the same length.
		const flip = craftPositionAt(path, route.departJd + route.tofDays / 2)!;
		expect(norm(sub(flip, start)) / total).toBeCloseTo(0.5, 1);
	});

	it('hands a swing-by crossing to the arc it is on', () => {
		const path = buildTrajectoryPath(EARTH, JUPITER, ASSIST_ROUTE, {
			centerId: SUN,
			vias: [VENUS]
		})!;
		const flyby = ASSIST_ROUTE.flybys![0];
		const at = craftPositionAt(path, flyby.jd)!;
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

	it('stands back further for a whole leg than for a burn on it', () => {
		const leg = pathViewpoint(PATH, ROUTE.departJd, ROUTE.arriveJd)!;
		const burn = pathViewpoint(PATH, ROUTE.departJd, ROUTE.departJd)!;
		expect(leg.rangeKm).toBeGreaterThan(burn.rangeKm);
		expect(burn.rangeKm).toBeGreaterThan(0);
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
