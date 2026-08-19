/**
 * Trips that stay at one body: what the arc between two of its orbits costs,
 * which pairs are trips at all, and the ends that need no arc.
 */

import { describe, expect, it } from 'vitest';
import { EARTH } from './test-fixtures';
import { buildRoute, type Route } from './route';
import { orbitChangeEnds } from './route';
import {
	circularSpeed,
	combinedBurn,
	orbitPeriodHours,
	parkingRadiusKm,
	planeChangeDv,
	type EndOrbit
} from './maneuvers';
import { hohmannArcDays } from './system-transfer';
import { buildTrajectoryPath } from './path';
import { craftPositionAt } from './path-sample';
import { cross, dot, norm, normalize, sub } from './vec3';

const J2000 = 2451545;
const GEO_RADIUS_KM = 42164;
const LOW: EndOrbit = { rPeriKm: parkingRadiusKm(EARTH), rApoKm: parkingRadiusKm(EARTH) };
const GEO: EndOrbit = { rPeriKm: GEO_RADIUS_KM, rApoKm: GEO_RADIUS_KM };
/** The transfer ellipse itself, as the planner offers it: low perigee, apogee
 *  at the stationary orbit. */
const GTO: EndOrbit = { rPeriKm: LOW.rPeriKm, rApoKm: GEO_RADIUS_KM };

const HOHMANN_DAYS = hohmannArcDays(EARTH.mu, LOW.rPeriKm, GEO_RADIUS_KM);

function route(
	from: EndOrbit | 'ground',
	to: EndOrbit | 'ground',
	tofDays = HOHMANN_DAYS
): Route | null {
	return buildRoute(EARTH, EARTH, J2000, tofDays, {
		orbitChange: true,
		departureMode: from === 'ground' ? 'surface' : 'orbit',
		arrivalMode: to === 'ground' ? 'landing' : 'capture',
		departureOrbit: from === 'ground' ? undefined : from,
		targetOrbit: to === 'ground' ? undefined : to
	});
}

function dvOf(r: Route | null, kind: string): number {
	return (r?.legs ?? [])
		.filter((leg) => leg.kind === kind)
		.reduce((sum, leg) => sum + leg.dvKms, 0);
}

describe('orbitChangeEnds', () => {
	it('refuses the same orbit twice — that is not a trip', () => {
		expect(
			orbitChangeEnds(EARTH, {
				departureMode: 'orbit',
				arrivalMode: 'capture',
				departureOrbit: LOW,
				targetOrbit: LOW
			})
		).toBeNull();
	});

	it('refuses a hop between two points on the ground, which is another arc', () => {
		expect(orbitChangeEnds(EARTH, { departureMode: 'surface', arrivalMode: 'landing' })).toBeNull();
	});

	it('refuses a flyby of the body you are already at', () => {
		expect(
			orbitChangeEnds(EARTH, { departureMode: 'orbit', arrivalMode: 'flyby', departureOrbit: LOW })
		).toBeNull();
	});

	it('leaves the low side climbing and the high side coming down', () => {
		const up = orbitChangeEnds(EARTH, {
			departureMode: 'orbit',
			arrivalMode: 'capture',
			departureOrbit: LOW,
			targetOrbit: GEO
		});
		expect(up?.climb).toBe(true);
		expect(up?.rFromKm).toBeCloseTo(LOW.rPeriKm, 3);
		expect(up?.rToKm).toBeCloseTo(GEO_RADIUS_KM, 3);

		const down = orbitChangeEnds(EARTH, {
			departureMode: 'orbit',
			arrivalMode: 'capture',
			departureOrbit: GEO,
			targetOrbit: LOW
		});
		expect(down?.climb).toBe(false);
		expect(down?.rFromKm).toBeCloseTo(GEO_RADIUS_KM, 3);
		expect(down?.rToKm).toBeCloseTo(LOW.rPeriKm, 3);
	});
});

describe('a trip between two orbits about one body', () => {
	// The textbook figures for a low-Earth-to-geostationary Hohmann pair: 2.46
	// km/s to leave, 1.47 to circularise at the top.
	it('prices the low orbit to stationary climb as the Hohmann pair', () => {
		const r = route(LOW, GEO);
		expect(dvOf(r, 'injection')).toBeCloseTo(2.46, 1);
		expect(dvOf(r, 'capture')).toBeCloseTo(1.47, 1);
	});

	it('costs the same coming back down', () => {
		const up = route(LOW, GEO)?.totalDvKms ?? 0;
		const down = route(GEO, LOW)?.totalDvKms ?? 0;
		expect(down).toBeCloseTo(up, 2);
	});

	it('owes nothing on arrival when the arc already is the orbit asked for', () => {
		// Injecting from a low orbit onto the transfer ellipse leaves the craft on
		// it — there is no second burn until it decides to circularise.
		const r = route(LOW, GTO);
		expect(dvOf(r, 'injection')).toBeCloseTo(2.46, 1);
		expect(dvOf(r, 'capture')).toBeCloseTo(0, 3);
	});

	it('charges the circularisation alone from the transfer ellipse to the stationary orbit', () => {
		const r = route(GTO, GEO);
		expect(r?.totalDvKms).toBeCloseTo(1.47, 1);
	});

	it('has nothing slower than the half-ellipse', () => {
		expect(route(LOW, GEO, HOHMANN_DAYS * 1.1)).toBeNull();
	});

	it('costs more the faster the climb is asked to be', () => {
		const slow = route(LOW, GEO, HOHMANN_DAYS)?.totalDvKms ?? 0;
		const quick = route(LOW, GEO, HOHMANN_DAYS * 0.5)?.totalDvKms ?? 0;
		expect(quick).toBeGreaterThan(slow);
	});

	it('stays bound to the body — nothing here is a launch to anywhere', () => {
		expect(route(LOW, GEO)?.c3Km2S2).toBeLessThan(0);
		expect(route(LOW, GEO)?.vInfDepKms).toBe(0);
	});
});

describe('the arc it draws', () => {
	const pathOf = (r: Route | null) =>
		r ? buildTrajectoryPath(EARTH, EARTH, r, { centerId: EARTH.id, orbitChange: true }) : null;

	it('runs from the orbit left to the one arrived at', () => {
		const path = pathOf(route(LOW, GEO));
		const points = path?.arcs[0].points ?? [];
		expect(norm(points[0])).toBeCloseTo(LOW.rPeriKm, 0);
		expect(norm(points[points.length - 1])).toBeCloseTo(GEO_RADIUS_KM, 0);
	});

	it('reads the same arc backwards coming down', () => {
		const path = pathOf(route(GEO, LOW));
		const points = path?.arcs[0].points ?? [];
		expect(norm(points[0])).toBeCloseTo(GEO_RADIUS_KM, 0);
		expect(norm(points[points.length - 1])).toBeCloseTo(LOW.rPeriKm, 0);
	});

	it('lies in the body’s own equator, the one plane the model can claim', () => {
		const path = pathOf(route(LOW, GEO));
		const pole = normalize(EARTH.poleEcliptic ?? [0, 0, 1]);
		for (const point of path?.arcs[0].points ?? []) {
			expect(Math.abs(dot(normalize(point), pole))).toBeLessThan(1e-9);
		}
	});

	it('is dated by the trip it draws, end to end', () => {
		const r = route(LOW, GEO);
		const arc = pathOf(r)?.arcs[0];
		expect(arc?.jds[0]).toBeCloseTo(r?.departJd ?? 0, 6);
		expect(arc?.jds[arc.jds.length - 1]).toBeCloseTo(r?.arriveJd ?? 0, 6);
	});

	it('coasts round at one radius where a single burn joins the ends', () => {
		const points = pathOf(route('ground', LOW))?.arcs[0].points ?? [];
		expect(points.length).toBeGreaterThan(2);
		for (const point of points) expect(norm(point)).toBeCloseTo(LOW.rPeriKm, 6);
		// Half a turn: the far end is on the other side of the body.
		expect(dot(normalize(points[0]), normalize(points[points.length - 1]))).toBeCloseTo(-1, 6);
	});
});

describe('the orbits at its ends', () => {
	const pathOf = (r: Route | null) =>
		r ? buildTrajectoryPath(EARTH, EARTH, r, { centerId: EARTH.id, orbitChange: true }) : null;
	/** A Molniya: the shape and the plane both named, and neither one flat. */
	const MOLNIYA: EndOrbit = {
		rPeriKm: EARTH.radiusKm + 600,
		rApoKm: EARTH.radiusKm + 39750,
		incDeg: 63.4
	};
	const toMolniya = () =>
		buildRoute(EARTH, EARTH, J2000, 0.22, {
			orbitChange: true,
			departureMode: 'surface',
			arrivalMode: 'capture',
			targetOrbit: MOLNIYA
		});

	// The arc and the ring share one point and nothing else fixes either, so the
	// ring hangs off it. Placed by the direction the arc came in from instead —
	// which is across the orbit at an apsis, not along it — the ring comes out a
	// quarter turn round and the trip ends beside the orbit it was flown to.
	it('meets the orbit it ends in, at the apsis they share', () => {
		const path = pathOf(toMolniya())!;
		const arc = path.arcs[0];
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;
		const last = arc.points[arc.points.length - 1];
		expect(Math.min(...end.points.map((p) => norm(sub(p, last))))).toBeLessThan(1);
		// It is the high point of the orbit that the climb arrives at.
		expect(norm(last)).toBeCloseTo(MOLNIYA.rApoKm, 6);
		const apo = end.points.reduce((far, p) => (norm(p) > norm(far) ? p : far), end.points[0]);
		expect(dot(normalize(apo), normalize(last))).toBeCloseTo(1, 9);
	});

	// The arc is flown in the equator because no node is tracked, but the orbit it
	// ends in named a plane and the trip was charged for turning into it. Drawn
	// flat as well, the picture is of a trip that never made the burn it paid for.
	it('leans the ring into the plane the trip named, from the point they share', () => {
		const path = pathOf(toMolniya())!;
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;
		const pole = normalize(EARTH.poleEcliptic!);
		const normal = normalize(
			cross(sub(end.points[24], end.points[0]), sub(end.points[48], end.points[0]))
		);
		expect((Math.acos(Math.abs(dot(normal, pole))) * 180) / Math.PI).toBeCloseTo(63.4, 3);
		// The point the arc hands over at is the one place the two planes meet, so
		// it is a node of this one — the only place the turn could be made.
		const last = path.arcs[0].points[path.arcs[0].points.length - 1];
		expect(Math.abs(dot(last, pole))).toBeLessThan(1e-6);
	});

	// The craft keeps flying after it arrives. Read as if the trip were over at
	// the last arc sample, the marker has nowhere to be and holds still on the
	// screen for as long as anyone watches.
	it('goes on round the orbit it arrived in', () => {
		const r = toMolniya()!;
		const path = pathOf(r)!;
		const revolution = orbitPeriodHours(EARTH.mu, MOLNIYA) / 24;
		const radii = [0.1, 0.3, 0.5, 0.7, 0.9].map((f) => {
			const at = craftPositionAt(path, r.arriveJd + revolution * f);
			expect(at).not.toBeNull();
			return norm(at!.r);
		});
		// Down from the high point it arrives at and back up again, over the two
		// radii the orbit is made of.
		expect(Math.min(...radii)).toBeLessThan(MOLNIYA.rApoKm / 2);
		expect(Math.max(...radii)).toBeGreaterThan(MOLNIYA.rApoKm * 0.9);
		for (const radius of radii) {
			expect(radius).toBeGreaterThan(MOLNIYA.rPeriKm - 1);
			expect(radius).toBeLessThan(MOLNIYA.rApoKm + 1);
		}
	});

	// Coming down, the arc arrives at the low point instead — the same rule read
	// the other way, and the one that keeps a descent from drawing its ring
	// upside down.
	it('joins the low point of an orbit it drops into', () => {
		const path = pathOf(route(GEO, GTO))!;
		const arc = path.arcs[0];
		const end = path.endOrbits.find((e) => e.at === 'arrival')!;
		const last = arc.points[arc.points.length - 1];
		expect(norm(last)).toBeCloseTo(GTO.rPeriKm, 6);
		expect(Math.min(...end.points.map((p) => norm(sub(p, last))))).toBeLessThan(1);
		const peri = end.points.reduce((near, p) => (norm(p) < norm(near) ? p : near), end.points[0]);
		expect(dot(normalize(peri), normalize(last))).toBeCloseTo(1, 9);
	});
});

describe('ends that need no arc between them', () => {
	it('reaching orbit from the ground is the ascent and nothing else', () => {
		const r = route('ground', LOW);
		expect(dvOf(r, 'ascent')).toBeGreaterThan(8);
		expect(dvOf(r, 'injection')).toBeCloseTo(0, 6);
		expect(dvOf(r, 'capture')).toBeCloseTo(0, 6);
		expect(r?.totalDvKms).toBeCloseTo(dvOf(r, 'ascent'), 6);
	});

	it('coming down from that orbit is the descent and nothing else', () => {
		const r = route(LOW, 'ground');
		expect(dvOf(r, 'injection')).toBeCloseTo(0, 6);
		// Asked for nothing from the air, so the landing cancels the orbit on the
		// engine — the ascent run backwards, which is what it costs.
		expect(dvOf(r, 'descent')).toBeGreaterThan(circularSpeed(EARTH.mu, LOW.rPeriKm));
		expect(r?.totalDvKms).toBeCloseTo(dvOf(r, 'descent'), 6);
	});

	it('lands on the air when the air is asked for', () => {
		const engine = route(LOW, 'ground')?.totalDvKms ?? 0;
		const parachute =
			buildRoute(EARTH, EARTH, J2000, 1, {
				orbitChange: true,
				departureMode: 'orbit',
				arrivalMode: 'landing',
				departureOrbit: LOW,
				aero: 'aerocapture'
			})?.totalDvKms ?? 0;
		expect(parachute).toBeLessThan(engine / 10);
	});

	it('takes half a turn of the orbit it is flown from', () => {
		const r = route('ground', LOW);
		const periodMin = orbitPeriodHours(EARTH.mu, LOW) * 60;
		expect((r?.tofDays ?? 0) * 24 * 60).toBeCloseTo(periodMin / 2, 6);
	});

	it('comes down from wherever the craft is, even below the parking orbit', () => {
		const low: EndOrbit = { rPeriKm: EARTH.radiusKm + 120, rApoKm: EARTH.radiusKm + 120 };
		expect(route(low, 'ground')?.totalDvKms).toBeGreaterThan(0);
	});
});

describe('a turn between two planes', () => {
	it('makes two planes at one radius a trip: the turn between them', () => {
		const r = route({ ...LOW, incDeg: 0 }, { ...LOW, incDeg: 45 })!;
		expect(r).not.toBeNull();
		expect(r.totalDvKms).toBeCloseTo(planeChangeDv(circularSpeed(EARTH.mu, LOW.rPeriKm), 45), 6);
		// Flipping all the way round to retrograde costs twice the orbit's speed.
		const flip = route({ ...LOW, incDeg: 0 }, { ...LOW, incDeg: 180 })!;
		expect(flip.totalDvKms).toBeCloseTo(2 * circularSpeed(EARTH.mu, LOW.rPeriKm), 6);
	});

	it('prices matched planes exactly as free ones', () => {
		const named = route({ ...LOW, incDeg: 51.6 }, { ...GEO, incDeg: 51.6 })!;
		const free = route(LOW, GEO)!;
		expect(named.totalDvKms).toBeCloseTo(free.totalDvKms, 12);
	});

	it('makes the turn at the far end of the arc, where it is cheapest', () => {
		const turned = route({ ...LOW, incDeg: 0 }, { ...GEO, incDeg: 28.6 })!;
		const flat = route({ ...LOW, incDeg: 0 }, { ...GEO, incDeg: 0 })!;
		// The climb out is the same arc either way; the far burn absorbs the turn.
		expect(dvOf(turned, 'injection')).toBeCloseTo(dvOf(flat, 'injection'), 12);
		expect(dvOf(turned, 'capture')).toBeGreaterThan(dvOf(flat, 'capture'));
		// The arc tops out slower than the ring by exactly the flat burn, so the
		// turned burn is the law of cosines between those two speeds.
		const vGeo = circularSpeed(EARTH.mu, GEO_RADIUS_KM);
		expect(dvOf(turned, 'capture')).toBeCloseTo(
			combinedBurn(vGeo - dvOf(flat, 'capture'), vGeo, 28.6),
			3
		);
	});

	it('launches into the plane it can, and turns the rest out in the arc', () => {
		const geo = (incDeg: number | undefined, latDeg?: number) =>
			buildRoute(EARTH, EARTH, J2000, HOHMANN_DAYS, {
				orbitChange: true,
				departureMode: 'surface',
				arrivalMode: 'capture',
				targetOrbit: incDeg === undefined ? GEO : { ...GEO, incDeg },
				departureSiteLatDeg: latDeg
			})!;
		// An equatorial target from an inclined pad: the ascent flies the pad's
		// own latitude and the circularisation burn carries the 28.6° turn —
		// the split every geostationary mission flies.
		const cape = geo(0, 28.6);
		expect(dvOf(cape, 'ascent')).toBeCloseTo(dvOf(geo(undefined, 28.6), 'ascent'), 12);
		expect(dvOf(cape, 'capture')).toBeGreaterThan(dvOf(geo(0, 0), 'capture'));
		// A polar target instead costs its spin on the way up, not a turn later.
		const polar = geo(90, 28.6);
		expect(dvOf(polar, 'ascent')).toBeGreaterThan(dvOf(cape, 'ascent'));
		expect(dvOf(polar, 'capture')).toBeCloseTo(dvOf(geo(undefined, 28.6), 'capture'), 12);
	});

	it('charges a landing out of a polar orbit for the ground speed it cannot ride', () => {
		const land = (incDeg?: number) =>
			buildRoute(EARTH, EARTH, J2000, HOHMANN_DAYS, {
				orbitChange: true,
				departureMode: 'orbit',
				arrivalMode: 'landing',
				departureOrbit: incDeg === undefined ? GEO : { ...GEO, incDeg },
				targetSiteLatDeg: 0
			})!;
		expect(dvOf(land(90), 'descent')).toBeGreaterThan(dvOf(land(0), 'descent'));
		expect(dvOf(land(undefined), 'descent')).toBeCloseTo(dvOf(land(0), 'descent'), 12);
	});
});
