/**
 * Where a passage hands over to an orbit that has named its argument of
 * periapsis.
 *
 * An end reached from outside the body has two free rotations: the plane the
 * hyperbola is flown in, which may be turned about the asymptote, and the
 * longitude of the orbit's own node line, which nothing in the model fixes. An
 * orbit saying nothing about its low point spends both on convenience — the
 * passage keeps the crossing's plane, and the orbit leans towards it.
 *
 * An orbit that does say has one thing to buy with them. The burn is made at
 * the passage's low point, which becomes the orbit's; the craft then coasts to
 * where the two planes cross and turns. Rotating a plane about that crossing
 * moves the low point round relative to the equator, and so moves the named
 * angle — the whole of what buys a high point over one hemisphere. What is
 * left over is one free parameter, spent on making the turn as cheap as it can
 * be, which is out near the top where the orbit is slow.
 *
 * So naming the angle costs something but rarely much: a small turn far out
 * swings the line of apsides a long way. The price and the drawing both read
 * the answer from here, so they agree about which orbit was flown.
 */

import { equatorialTiltDeg, type TravelBody } from './body';
import {
	asymptoteTurnDeg,
	NO_TURN,
	orbitSpeedAtRadius,
	type EndOrbit,
	type EndTurn
} from './maneuvers';
import {
	add,
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

/** How the family is searched for its cheapest member: a sweep coarse enough
 *  not to step over a stretch of it, then rounds of local narrowing. */
const SWEEP_STEPS = 24;
const REFINE_ROUNDS = 4;
const REFINE_SPLIT = 4;

/**
 * The plane at inclination `incDeg` whose *ascending* node lies along `node`,
 * as its normal. Tipped the one way that leaves the craft climbing north
 * through the node rather than falling south through it.
 */
export function planeAboutNode(pole: Vec3, node: Vec3, incDeg: number): Vec3 {
	const inc = incDeg * (Math.PI / 180);
	const east = cross(pole, node);
	return normalize(add(scale(pole, Math.cos(inc)), scale(east, -Math.sin(inc))));
}

/** Whether an orbit actually says where its low point sits. It takes all three:
 *  an angle to name, a plane to measure it in, and two ends far enough apart
 *  for the orbit to have a low point at all. */
export function namesArgPeri(orbit: EndOrbit): boolean {
	return (
		orbit.argPeriDeg !== undefined && orbit.incDeg !== undefined && orbit.rApoKm > orbit.rPeriKm
	);
}

/** Where a passage and the orbit it hands over to cross, and what crossing
 *  there costs. */
export interface PassageNode {
	/** Direction of the crossing from the body — where the turn is made. */
	node: Vec3;
	/** The plane the passage is flown in, as its angular momentum. */
	normal: Vec3;
	/** The plane the orbit is flown in, likewise. */
	orbitNormal: Vec3;
	/** True anomaly the orbit is at when it reaches the crossing, radians. */
	nuNode: number;
	/** Radius of the crossing, km — the speed the turn is paid at. */
	radiusKm: number;
	/** Angle between the two planes, degrees. */
	turnDeg: number;
	/** Δv that turn costs where it is made, km/s. */
	dvKms: number;
}

export interface PassageNodeRequest {
	body: TravelBody;
	orbit: EndOrbit;
	/** Excess velocity at this end, km/s. Only its direction is read. */
	vInf: Vec3;
	/** Radius the passage is flown at, km — the orbit's own periapsis for an
	 *  engine arrival, lower for a pass through the air. */
	rPeriKm: number;
	outward: boolean;
}

/**
 * The cheapest crossing an ω-named end can be turned at, or null where there is
 * none.
 *
 * Only one parameter is really free. Two rotations start out so — the passage
 * plane about the asymptote, and the orbit's node line round the equator — and
 * the coast from the burn to the turn spends one of them, which leaves the
 * crossing free to slide along the orbit. Where it stops is the whole of the
 * choice made here, and it is made on cost: a turn out where the orbit is slow
 * is a cheap one.
 *
 * Null covers every case the caller should go on treating as free: an orbit
 * naming no angle, a body with no published pole, an equatorial plane with no
 * node to measure from, and a geometry with no crossing that works. The end
 * then draws and prices as though the angle had never been named.
 */
export function passageNode(request: PassageNodeRequest): PassageNode | null {
	const { body, orbit, vInf, rPeriKm, outward } = request;
	if (!namesArgPeri(orbit) || !body.poleEcliptic) return null;
	const speed = norm(vInf);
	if (!(speed > 0) || !(body.mu > 0) || !(rPeriKm > 0)) return null;

	const pole = normalize(body.poleEcliptic);
	if (!(norm(pole) > 0)) return null;
	const inc = orbit.incDeg! * (Math.PI / 180);
	const sinInc = Math.sin(inc);
	const cosInc = Math.cos(inc);
	// An equatorial plane crosses the equator nowhere, so it has no node for the
	// angle to be measured from and nothing here to solve.
	if (!(Math.abs(sinInc) > 1e-9)) return null;
	const asymptote = normalize(vInf);

	// The conic the passage is: eccentricity from the excess speed at this
	// radius, and with it the angle its own low point sits at from the asymptote.
	const hyper = 1 + (rPeriKm * speed * speed) / body.mu;
	if (!(hyper > 1)) return null;
	const nuInf = Math.acos(-1 / hyper);

	// The asymptote's own height above the equator, and a frame to measure
	// longitude from it in. An exactly polar asymptote leaves longitude with
	// nothing to mean, and is left to the free answer.
	const sinLatA = dot(asymptote, pole);
	const cosLatA = Math.sqrt(Math.max(0, 1 - sinLatA * sinLatA));
	if (!(cosLatA > 1e-9)) return null;
	const alongA = normalize(sub(asymptote, scale(pole, sinLatA)));
	const acrossA = cross(pole, alongA);

	const arg = orbit.argPeriDeg! * (Math.PI / 180);
	const e = (orbit.rApoKm - orbit.rPeriKm) / (orbit.rApoKm + orbit.rPeriKm);
	const semiLatus = (2 * orbit.rPeriKm * orbit.rApoKm) / (orbit.rPeriKm + orbit.rApoKm);
	const radiusAt = (nu: number) => semiLatus / (1 + e * Math.cos(nu));

	/**
	 * The crossing the orbit reaches at true anomaly `nu`, and what turning there
	 * costs — all of it in angles, none of it in vectors.
	 *
	 * Nothing is searched for: three classical relations settle the geometry. The
	 * orbit is at argument of latitude ω + ν when it gets there, which fixes how
	 * far above the equator the crossing sits; the coast from the passage's low
	 * point fixes how far round from the asymptote it sits; and those two leave
	 * only a longitude, which the first of them then fixes as well — to one side
	 * of the asymptote or the other, both of which are tried here.
	 *
	 * The turn is the angle between the two paths where they cross, and a path's
	 * heading there follows from the lean of its plane alone. So the whole family
	 * can be priced without building a single vector, and without an inverse
	 * trigonometric function either — the half-angle the Δv wants comes straight
	 * off the cosine. That is what keeps this cheap enough to run in the middle of
	 * a porkchop.
	 */
	const priceAt = (nu: number): Crossing | null => {
		const u = arg + nu;
		const sinU = Math.sin(u);
		const cosU = Math.cos(u);
		const sinLat = sinInc * sinU;
		const cosLat = Math.sqrt(Math.max(0, 1 - sinLat * sinLat));
		if (!(cosLat > 1e-9)) return null;
		// How far round from the asymptote the coast has come by then. Only the
		// near half of a turn is an angle between two directions; the far half is
		// the same geometry flown the other way about, and it comes up again at
		// another true anomaly.
		const swept = wrap2Pi(outward ? nu - nuInf : nu + nuInf - Math.PI);
		if (!(swept > 1e-9) || !(swept < Math.PI - 1e-9)) return null;
		const sinSwept = Math.sin(swept);
		const cosLon = (Math.cos(swept) - sinLat * sinLatA) / (cosLat * cosLatA);
		if (!(Math.abs(cosLon) <= 1)) return null;
		const sinLon = Math.sqrt(Math.max(0, 1 - cosLon * cosLon));

		// Either end of the crossing line will do — turning at one leaves the orbit
		// exactly where turning at the other does — so the trip takes the slower,
		// which is the cheaper.
		const nuNode = radiusAt(nu + Math.PI) > radiusAt(nu) ? nu + Math.PI : nu;
		const radiusKm = radiusAt(nuNode);
		const speedKms = orbitSpeedAtRadius(body.mu, orbit, radiusKm);

		// Heading of each path where they meet, north-referenced.
		const sinOrbit = cosInc / cosLat;
		const cosOrbit = (sinInc * cosU) / cosLat;
		const cosPass = (sinLat * cosLon * cosLatA - sinLatA * cosLat) / sinSwept;
		let best: Crossing | null = null;
		for (const side of SIDES) {
			const sinPass = (side * cosLatA * sinLon) / sinSwept;
			const cosTurn = cosOrbit * cosPass + sinOrbit * sinPass;
			// A pure plane change is twice the speed times the sine of half the turn,
			// and the half-angle comes off the cosine without an angle in between.
			const dvKms = 2 * speedKms * Math.sqrt(Math.max(0, (1 - cosTurn) / 2));
			if (!best || dvKms < best.dvKms) {
				best = {
					nu,
					sinLat,
					cosLat,
					cosLon,
					sinLon: side * sinLon,
					sinU,
					cosU,
					nuNode,
					radiusKm,
					cosTurn,
					dvKms
				};
			}
		}
		return best;
	};

	/** The same crossing as directions in space, once it is the one being kept.
	 *  Built rather than searched for, so the answer is checked rather than
	 *  trusted: the coast really does leave the burn and arrive here. */
	const build = (found: Crossing): PassageNode | null => {
		const along = add(scale(alongA, found.cosLon), scale(acrossA, found.sinLon));
		const node = add(scale(along, found.cosLat), scale(pole, found.sinLat));
		const off = cross(asymptote, node);
		if (!(norm(off) > 1e-9)) return null;
		const normal = normalize(off);
		// Where the orbit crosses the equator: that far back round the equator from
		// the crossing's own longitude.
		const back = Math.atan2(found.sinU * cosInc, found.cosU);
		const cosBack = Math.cos(back);
		const sinBack = Math.sin(back);
		const ascending = add(
			scale(alongA, found.cosLon * cosBack + found.sinLon * sinBack),
			scale(acrossA, found.sinLon * cosBack - found.cosLon * sinBack)
		);
		const orbitNormal = planeAboutNode(pole, ascending, orbit.incDeg!);
		const low = outward
			? rotateAbout(asymptote, normal, -nuInf)
			: rotateAbout(scale(asymptote, -1), normal, nuInf);
		if (Math.abs(wrapPi(angleAbout(low, node, normal) - found.nu)) > 1e-6) return null;
		return {
			node: found.nuNode === found.nu ? node : scale(node, -1),
			normal,
			orbitNormal,
			nuNode: found.nuNode,
			radiusKm: found.radiusKm,
			turnDeg: (Math.acos(Math.max(-1, Math.min(1, found.cosTurn))) * 180) / Math.PI,
			dvKms: found.dvKms
		};
	};

	// Only half a turn of true anomaly is reachable at all — the half over which
	// the coast has swept less than a straight angle from the asymptote — so that
	// is the whole of what gets searched. Inside it the family runs over stretches
	// rather than the lot, and a sweep coarse enough to stay cheap finds every
	// stretch before a local pass walks to the bottom of whichever one wins.
	let best: Crossing | null = null;
	const consider = (nu: number) => {
		const here = priceAt(nu);
		if (here && (!best || here.dvKms < best.dvKms)) best = here;
	};
	const from = outward ? nuInf : Math.PI - nuInf;
	const step = Math.PI / SWEEP_STEPS;
	for (let i = 1; i < SWEEP_STEPS; i++) consider(from + i * step);
	if (!best) return null;
	for (let round = 0, span = step; round < REFINE_ROUNDS; round++, span /= REFINE_SPLIT) {
		const centre = (best as Crossing).nu;
		for (let i = -REFINE_SPLIT; i <= REFINE_SPLIT; i++) {
			if (i !== 0) consider(centre + (span * i) / REFINE_SPLIT);
		}
	}
	return build(best);
}

/** Which side of the asymptote the crossing is taken on. */
const SIDES = [1, -1];

/** One member of the family, priced but not yet drawn. */
interface Crossing {
	nu: number;
	sinLat: number;
	cosLat: number;
	cosLon: number;
	sinLon: number;
	/** Sine and cosine of the argument of latitude at the crossing. */
	sinU: number;
	cosU: number;
	nuNode: number;
	radiusKm: number;
	cosTurn: number;
	dvKms: number;
}

function wrap2Pi(angle: number): number {
	return ((angle % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
}

function wrapPi(angle: number): number {
	return wrap2Pi(angle + Math.PI) - Math.PI;
}

/**
 * The turn an end of a trip owes for the plane it has to be reached in.
 *
 * An orbit that says nothing about its low point is free to swing its node line
 * under the asymptote, so it owes only what its lean falls short of the
 * asymptote's declination by — usually nothing. One that has named where its
 * low point sits has spent that freedom, and owes the turn that buys the angle
 * back.
 *
 * A named angle no crossing can reach falls back to the free answer, which is
 * also what is then drawn: the orbit is entered as though it had never said.
 */
export function endTurn(request: {
	body: TravelBody;
	orbit: EndOrbit | undefined;
	vInf: Vec3;
	/** Radius the passage is flown at, km — the orbit's own periapsis unless the
	 *  air is doing the capturing. */
	rPeriKm?: number;
	outward: boolean;
}): EndTurn {
	const { body, orbit, vInf, outward } = request;
	if (!orbit) return NO_TURN;
	const solved = passageNode({
		body,
		orbit,
		vInf,
		rPeriKm: request.rPeriKm ?? orbit.rPeriKm,
		outward
	});
	if (solved) return { deg: solved.turnDeg, radiusKm: solved.radiusKm };
	return { deg: asymptoteTurnDeg(orbit, equatorialTiltDeg(body, vInf)) };
}
