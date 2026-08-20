/**
 * Reaching an orbit that has named where its low point sits, from outside the
 * body: which crossing the turn is made at, and that the price and the picture
 * agree about it.
 */

import { describe, expect, it } from 'vitest';
import { EARTH, MARS } from './test-fixtures';
import { endTurn, passageNode } from './passage-node';
import {
	orbitSpeedAtRadius,
	parkingOrbit,
	planeChangeDv,
	planeTurnRadiusKm,
	type EndOrbit
} from './maneuvers';
import { buildRoute } from './route';
import { buildTrajectoryPath } from './path';
import {
	angleAbout,
	cross,
	dot,
	norm,
	normalize,
	rotateAbout,
	scale,
	sub,
	type Vec3
} from './vec3';

const POLE = normalize(MARS.poleEcliptic!);
const MOL = (argPeriDeg?: number, incDeg = 63.4): EndOrbit => ({
	rPeriKm: MARS.radiusKm + 500,
	rApoKm: MARS.radiusKm + 20000,
	incDeg,
	argPeriDeg
});
const ASYMPTOTES: Vec3[] = [
	[2.5, 0.7, 0.3],
	[1, -2, 0.9],
	[-1.5, 1.5, -0.2],
	[0.4, 0.2, 2.6]
];

const solve = (orbit: EndOrbit, vInf: Vec3, outward = false) =>
	passageNode({ body: MARS, orbit, vInf, rPeriKm: orbit.rPeriKm, outward });

/** Latitude a direction sits at above the body's equator, degrees. */
const latOf = (v: Vec3) => (Math.asin(dot(normalize(v), POLE)) * 180) / Math.PI;

describe('passageNode', () => {
	// Every one of these is an orbit with nothing to say about its low point, so
	// there is no crossing to pin and the end is reached however it likes.
	it('has nothing to solve for an orbit that names no angle', () => {
		expect(solve(MOL(), ASYMPTOTES[0])).toBeNull();
		expect(solve(parkingOrbit(MARS), ASYMPTOTES[0])).toBeNull();
		// A circle has no low point, and an equatorial plane no node to measure from.
		expect(solve({ ...MOL(270), rApoKm: MOL().rPeriKm }, ASYMPTOTES[0])).toBeNull();
		expect(solve(MOL(270, 0), ASYMPTOTES[0])).toBeNull();
		// A body whose pole nobody has published has no equator to lean against.
		expect(
			passageNode({
				body: { ...MARS, poleEcliptic: undefined },
				orbit: MOL(270),
				vInf: ASYMPTOTES[0],
				rPeriKm: MOL().rPeriKm,
				outward: false
			})
		).toBeNull();
	});

	// The whole of what the solve claims: one point is shared by the passage and
	// the orbit, both are really flown through it, and the orbit that comes out
	// the far side is the one that was asked for.
	it('lands the coast on the crossing at the angle the orbit named', () => {
		for (const vInf of ASYMPTOTES) {
			for (const argPeriDeg of [0, 45, 90, 135, 180, 225, 270, 315]) {
				for (const outward of [false, true]) {
					const orbit = MOL(argPeriDeg);
					const solved = solve(orbit, vInf, outward);
					expect(solved).not.toBeNull();
					const { node, normal, orbitNormal, nuNode, radiusKm } = solved!;

					// Both planes hold the crossing, or there is no turn to make there.
					expect(dot(node, normal)).toBeCloseTo(0, 9);
					expect(dot(node, orbitNormal)).toBeCloseTo(0, 9);
					// And the orbit still leans the way it was told to.
					expect((Math.acos(dot(orbitNormal, POLE)) * 180) / Math.PI).toBeCloseTo(63.4, 6);

					// The coast starts at the passage's own low point and reaches the
					// crossing exactly where the orbit says it is.
					const asymptote = normalize(vInf);
					const e = 1 + (orbit.rPeriKm * dot(vInf, vInf)) / MARS.mu;
					const nuInf = Math.acos(-1 / e);
					const low = outward
						? rotateAbout(asymptote, normal, -nuInf)
						: rotateAbout(scale(asymptote, -1), normal, nuInf);
					const reached = angleAbout(low, node, normal);
					expect(Math.cos(reached)).toBeCloseTo(Math.cos(nuNode), 6);
					expect(Math.sin(reached)).toBeCloseTo(Math.sin(nuNode), 6);

					// The named angle measures from the ascending node to the low point,
					// and the crossing is charged at the radius the orbit has there.
					const ascending = normalize(cross(POLE, orbitNormal));
					const periapsis = rotateAbout(node, orbitNormal, -nuNode);
					const arg = (angleAbout(ascending, periapsis, orbitNormal) * 180) / Math.PI;
					expect(Math.cos((arg - argPeriDeg) * (Math.PI / 180))).toBeCloseTo(1, 6);
					const semiLatus = (2 * orbit.rPeriKm * orbit.rApoKm) / (orbit.rPeriKm + orbit.rApoKm);
					const ecc = (orbit.rApoKm - orbit.rPeriKm) / (orbit.rApoKm + orbit.rPeriKm);
					expect(radiusKm).toBeCloseTo(semiLatus / (1 + ecc * Math.cos(nuNode)), 3);
				}
			}
		}
	});

	// The family is priced in angles alone, without building a vector, because
	// doing it per cell of a porkchop is the difference between a search and a
	// hang. That shortcut is only worth having while it agrees with the geometry
	// it stands in for, so it is checked against it here rather than trusted.
	it('prices the turn as the geometry has it', () => {
		for (const vInf of ASYMPTOTES) {
			for (const argPeriDeg of [0, 45, 90, 135, 180, 225, 270, 315]) {
				for (const outward of [false, true]) {
					const solved = solve(MOL(argPeriDeg), vInf, outward)!;
					const between =
						(Math.acos(Math.max(-1, Math.min(1, dot(solved.normal, solved.orbitNormal)))) * 180) /
						Math.PI;
					expect(solved.turnDeg).toBeCloseTo(between, 6);
					expect(solved.dvKms).toBeCloseTo(
						planeChangeDv(orbitSpeedAtRadius(MARS.mu, MOL(argPeriDeg), solved.radiusKm), between),
						9
					);
				}
			}
		}
	});

	// Spending the two free rotations on the angle leaves one over, and it goes
	// on making the turn cheap: out where the orbit is slow, a small turn swings
	// the line of apsides a long way.
	it('turns far out, where turning is cheap', () => {
		for (const argPeriDeg of [45, 90, 135, 270]) {
			const orbit = MOL(argPeriDeg);
			const solved = solve(orbit, ASYMPTOTES[0])!;
			// Well beyond the crossing an orbit is stuck with when its node line is
			// pinned to the equator, which is what the angle alone would fix — the
			// spare rotation goes on getting further out than that.
			expect(solved.radiusKm).toBeGreaterThan(planeTurnRadiusKm(orbit));
			// And it is the slowness that pays: the same turn made down at the low
			// point would cost twice over.
			expect(solved.dvKms * 2.5).toBeLessThan(
				planeChangeDv(orbitSpeedAtRadius(MARS.mu, orbit, orbit.rPeriKm), solved.turnDeg)
			);
		}
	});
});

describe('what an end owes', () => {
	// A free orbit swings its nodes under the asymptote and owes nothing; naming
	// the angle spends that freedom, and the turn is what buys it back.
	it('charges the named angle and nothing for a free one', () => {
		const free = endTurn({ body: MARS, orbit: MOL(), vInf: ASYMPTOTES[0], outward: false });
		expect(free.deg).toBe(0);
		const named = endTurn({ body: MARS, orbit: MOL(270), vInf: ASYMPTOTES[0], outward: false });
		expect(named.deg).toBeGreaterThan(0);
		expect(named.radiusKm).toBeDefined();
	});

	// An orbit free to put its low point anywhere can do everything one told where
	// to put it can, so naming the angle can only ever cost. Worth pinning: the
	// two are priced by different routes through the model, and a trip that got
	// cheaper for being told more would be nonsense on the face of it.
	it('never makes a trip cheaper for having been told more', () => {
		for (const vInf of ASYMPTOTES) {
			for (const incDeg of [20, 45, 63.4, 85]) {
				const shape = { ...MOL(undefined, incDeg) };
				const free = endTurn({ body: MARS, orbit: shape, vInf, outward: false });
				const freeDv = planeChangeDv(
					orbitSpeedAtRadius(MARS.mu, shape, free.radiusKm ?? planeTurnRadiusKm(shape)),
					free.deg
				);
				for (const argPeriDeg of [0, 60, 120, 180, 240, 300]) {
					const named = { ...shape, argPeriDeg };
					const owed = endTurn({ body: MARS, orbit: named, vInf, outward: false });
					const namedDv = planeChangeDv(
						orbitSpeedAtRadius(MARS.mu, named, owed.radiusKm ?? planeTurnRadiusKm(named)),
						owed.deg
					);
					expect(namedDv).toBeGreaterThanOrEqual(freeDv - 1e-9);
				}
			}
		}
	});

	it('owes nothing where there is no orbit to reach', () => {
		expect(endTurn({ body: MARS, orbit: undefined, vInf: ASYMPTOTES[0], outward: false }).deg).toBe(
			0
		);
	});
});

describe('an interplanetary arrival into a named orbit', () => {
	const arrive = (argPeriDeg?: number) => {
		const targetOrbit = MOL(argPeriDeg);
		const route = buildRoute(EARTH, MARS, 2451545, 500, {
			departureMode: 'orbit',
			arrivalMode: 'capture',
			targetOrbit
		})!;
		const path = buildTrajectoryPath(EARTH, MARS, route, {
			centerId: MARS.id,
			frame: 'planetary'
		})!;
		return { route, end: path.endOrbits.find((e) => e.at === 'arrival')! };
	};

	// The whole point of the field, now reached from another planet rather than
	// launched into: the high point hangs over the hemisphere it was asked to.
	it('hangs apoapsis over the hemisphere it names', () => {
		const highest = (argPeriDeg?: number) => {
			const { end } = arrive(argPeriDeg);
			return latOf(end.points.reduce((f, p) => (norm(p) > norm(f) ? p : f), end.points[0]));
		};
		expect(highest(270)).toBeCloseTo(63.4, 1);
		expect(highest(90)).toBeCloseTo(-63.4, 1);
		// Apsides on the node line put both of them on the equator.
		expect(highest(0)).toBeCloseTo(0, 1);
		expect(highest(180)).toBeCloseTo(0, 1);
	});

	// Naming the angle is not free, and the trip that pays for it is the one that
	// flies it: the coast hands over out at the crossing that was charged for,
	// not down at the burn.
	it('pays for the angle, and turns where it paid', () => {
		const free = arrive();
		for (const argPeriDeg of [0, 90, 180, 270]) {
			const named = arrive(argPeriDeg);
			expect(named.route.totalDvKms).toBeGreaterThan(free.route.totalDvKms);

			const turn = named.end.turn!;
			const handover = named.end.approach[turn.to - 1];
			// It lands on the ring it hands over to, which is the whole point of
			// solving the two planes together. Measured against the ring's own
			// sample spacing, since a ring drawn as a polyline is only ever that
			// near to any point on the orbit it stands for.
			const ring = named.end.points;
			const spacing = Math.max(...ring.slice(1).map((p, i) => norm(sub(p, ring[i]))));
			const gap = Math.min(...ring.map((p) => norm(sub(p, handover))));
			expect(gap).toBeLessThan(spacing);
			// And it is made far out, where turning is cheap, rather than at the
			// low point the passage came in on.
			expect(norm(handover)).toBeGreaterThan(MOL().rPeriKm * 3);
		}
	});
});
