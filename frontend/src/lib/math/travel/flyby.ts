/**
 * A swing-by: what passing close to a body does to a heliocentric velocity.
 *
 * Inside the body's sphere of influence the craft flies a hyperbola, which turns
 * its excess velocity without changing the speed. Back outside, that rotation
 * has been added to the body's own orbital motion, so the heliocentric velocity
 * changed for free. How far it can turn is set by how close the pass gets and
 * how fast the craft is going: slow passes close to a massive body turn a lot.
 *
 * Two arcs meeting at one body will rarely want exactly the same excess speed on
 * both sides, so the model is the powered swing-by — a burn at periapsis makes
 * up whatever the geometry cannot. The unpowered assist is the case where that
 * burn comes out zero, and it falls out of the same solve rather than needing a
 * branch of its own. This is the model ESA's GTOP problems use.
 */

import type { TravelBody } from './body';
import { norm, sub, type Vec3 } from './vec3';
import { FLYBY_MIN_ALTITUDE_KM } from './constants';
import { periapsisSpeed } from './maneuvers';

export interface FlybyPass {
	/** Which body was passed. */
	bodyId: string;
	/** When, JD. */
	jd: number;
	/** Height of closest approach above the mean radius, km. */
	altitudeKm: number;
	/** Δv the craft supplies at periapsis, km/s. Zero for a free assist. */
	dvKms: number;
	/** How far the pass turns the excess-velocity vector, degrees. */
	turnDeg: number;
	/** Excess speed going in and coming out, km/s. */
	vInfInKms: number;
	vInfOutKms: number;
}

/**
 * How far a pass at `rPeriKm` turns an approach with excess speed `vInfKms`,
 * radians. Zero at infinite distance, approaching π for a slow grazing pass.
 */
export function turnAngleRad(mu: number, rPeriKm: number, vInfKms: number): number {
	if (!(mu > 0) || !(rPeriKm > 0) || !(vInfKms > 0)) return 0;
	const e = 1 + (rPeriKm * vInfKms * vInfKms) / mu;
	return 2 * Math.asin(1 / e);
}

/** Closest a pass may get: clear of the atmosphere, or of the ground. */
export function minFlybyRadiusKm(body: TravelBody): number {
	return body.radiusKm + FLYBY_MIN_ALTITUDE_KM;
}

/**
 * Price the pass that joins an approach to a departure.
 *
 * The two excess-velocity vectors name what the swing-by has to do: turn the
 * approach through the angle between them, and make up the difference in speed.
 * Only the periapsis radius is free, and it fixes both — so it is solved for the
 * turn (bisection on a monotone function) and the leftover speed difference is
 * paid there as a burn, which is where it is cheapest.
 *
 * Returns null when even the lowest permitted pass cannot turn far enough. That
 * is a real answer, not a failure: it is why a slow craft cannot use Mars the
 * way it can use Jupiter.
 */
export function solveFlyby(
	body: TravelBody,
	vInfIn: Vec3,
	vInfOut: Vec3,
	maxRadiusKm = Infinity
): { dvKms: number; periapsisKm: number; turnRad: number } | null {
	const vIn = norm(vInfIn);
	const vOut = norm(vInfOut);
	if (!(vIn > 0) || !(vOut > 0)) return null;

	const cos =
		(vInfIn[0] * vInfOut[0] + vInfIn[1] * vInfOut[1] + vInfIn[2] * vInfOut[2]) / (vIn * vOut);
	const required = Math.acos(Math.max(-1, Math.min(1, cos)));

	// Total turn available at radius r: half of it on the way in, half on the way
	// out, each on its own branch's excess speed. Falls monotonically with r.
	const available = (r: number): number =>
		turnAngleRad(body.mu, r, vIn) / 2 + turnAngleRad(body.mu, r, vOut) / 2;

	const rMin = minFlybyRadiusKm(body);
	if (available(rMin) < required) return null;

	let rPeri: number;
	if (required <= 0) {
		// Nothing to turn: the pass exists only to change speed, and there is no
		// radius the geometry picks. Charge it at the ceiling, where the Oberth
		// help is least — a burn nowhere near a body is what this really is.
		rPeri = isFinite(maxRadiusKm) ? maxRadiusKm : rMin;
	} else if (available(maxRadiusKm) >= required) {
		rPeri = maxRadiusKm;
	} else {
		let lo = rMin;
		let hi = isFinite(maxRadiusKm) ? maxRadiusKm : rMin * 1e6;
		for (let i = 0; i < 60; i++) {
			const mid = (lo + hi) / 2;
			if (available(mid) >= required) lo = mid;
			else hi = mid;
		}
		rPeri = (lo + hi) / 2;
	}

	const dvKms = Math.abs(
		periapsisSpeed(body.mu, rPeri, vOut) - periapsisSpeed(body.mu, rPeri, vIn)
	);
	if (!isFinite(dvKms)) return null;
	return { dvKms, periapsisKm: rPeri, turnRad: required };
}

/** The excess velocity an arc arriving at `vArc` leaves the body with. */
export function excessVelocity(vArc: Vec3, vBody: Vec3): Vec3 {
	return sub(vArc, vBody);
}
