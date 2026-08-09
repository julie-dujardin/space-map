import { describe, it, expect } from 'vitest';
import { buildTrajectoryPath } from './path';
import { buildRoute } from './route';
import { buildAssistRoute } from './assist';
import { buildConstantThrustRoute } from './brachistochrone';
import { elementsToState } from './state';
import { hohmannTransferDays, nextTransferWindows } from './windows';
import { GM_SUN_KM3_S2 } from './constants';
import { norm, sub, type Vec3 } from './vec3';
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

	it('flies a held drive straight, flipping at the halfway point', () => {
		const route = buildConstantThrustRoute(EARTH, MARS, J2000, 0.1)!;
		const path = buildTrajectoryPath(EARTH, MARS, route, { centerId: SUN })!;
		expect(path.arcs.map((a) => a.kind)).toEqual(['boost', 'brake']);

		const start = path.arcs[0].points[0];
		const end = path.arcs[1].points[path.arcs[1].points.length - 1];
		const flip = path.arcs[0].points[path.arcs[0].points.length - 1];
		// Half the crossing is behind it at the flip, and the line is straight, so
		// every sample sits on the chord.
		expect(norm(sub(flip, start))).toBeCloseTo(norm(sub(end, flip)), 3);
		for (const point of path.arcs[0].points) {
			expect(norm(sub(point, start)) + norm(sub(end, point))).toBeCloseTo(norm(sub(end, start)), 3);
		}
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
