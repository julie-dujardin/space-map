/**
 * A swing-by: what passing close to a body does to a heliocentric velocity.
 * Inside the sphere of influence the craft flies a hyperbola that turns its
 * excess velocity without changing its speed; outside, that rotation is added
 * to the body's own motion, so the heliocentric velocity changes for free. A
 * slow pass close to a massive body turns the most.
 *
 * Two arcs meeting at one body rarely want the same excess speed on both
 * sides, so this models the powered swing-by — a periapsis burn makes up
 * whatever the geometry can't. Unpowered is just the case where that burn is
 * zero, falling out of the same solve. This is ESA's GTOP model.
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
 * Price the pass that joins an approach to a departure. The two excess-velocity
 * vectors set what the swing-by must do: turn through the angle between them
 * and make up the leftover speed. Only the periapsis radius is free, so it's
 * solved for the turn (bisection on a monotone function) and the speed gap is
 * paid there, where it's cheapest.
 *
 * Returns null when even the lowest permitted pass can't turn far enough — a
 * real answer, not a failure: why a slow craft can't use Mars like Jupiter.
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

	const rPeri = flybyPeriapsisKm(body.mu, minFlybyRadiusKm(body), maxRadiusKm, vIn, vOut, required);
	if (Number.isNaN(rPeri)) return null;

	const dvKms = flybyDvKms(body.mu, rPeri, vIn, vOut);
	if (!isFinite(dvKms)) return null;
	return { dvKms, periapsisKm: rPeri, turnRad: required };
}

/** What the pass costs once its radius is known: the speed the geometry could
 *  not supply, bought at periapsis where it is cheapest. */
export function flybyDvKms(mu: number, rPeriKm: number, vInKms: number, vOutKms: number): number {
	return Math.abs(periapsisSpeed(mu, rPeriKm, vOutKms) - periapsisSpeed(mu, rPeriKm, vInKms));
}

/**
 * The periapsis that turns `required` radians, km, or NaN if no permitted pass
 * turns that far. Split out of `solveFlyby` and returning a bare number since
 * the search calls it tens of thousands of times — the only iterating part of a
 * candidate route, so an object per call would mean an object per grid cell.
 *
 * The bracket keeps iteration short: each branch has a closed form,
 * r = (μ/v∞²)·(1/sin(δ/2) − 1), and the pass turns their average — so the
 * answer always lies between the two single-branch radii. Bisecting that tight
 * bracket takes dozens of steps; bisecting the full six-order-of-magnitude
 * radius range would take far more.
 */
export function flybyPeriapsisKm(
	mu: number,
	rMinKm: number,
	maxRadiusKm: number,
	vInKms: number,
	vOutKms: number,
	required: number
): number {
	// Half the turn on the way in and half on the way out, each on its own
	// branch's excess speed. Falls monotonically with r.
	const available = (r: number): number =>
		turnAngleRad(mu, r, vInKms) / 2 + turnAngleRad(mu, r, vOutKms) / 2;

	if (available(rMinKm) < required) return NaN;
	// Nothing to turn: the pass exists only to change speed, and no radius is
	// picked out. Charge it at the ceiling, where the Oberth help is least — a
	// burn nowhere near a body is what this really is.
	if (required <= 0) return isFinite(maxRadiusKm) ? maxRadiusKm : rMinKm;
	if (available(maxRadiusKm) >= required) return maxRadiusKm;

	const shape = 1 / Math.sin(required / 2) - 1;
	const rIn = (mu / (vInKms * vInKms)) * shape;
	const rOut = (mu / (vOutKms * vOutKms)) * shape;
	let lo = Math.max(rMinKm, Math.min(rIn, rOut));
	let hi = Math.min(maxRadiusKm, Math.max(rIn, rOut));
	if (!(hi > lo)) return Math.max(rMinKm, Math.min(maxRadiusKm, lo));

	for (let i = 0; i < 30 && hi - lo > lo * 1e-9; i++) {
		const mid = (lo + hi) / 2;
		if (available(mid) >= required) lo = mid;
		else hi = mid;
	}
	return (lo + hi) / 2;
}

/** The excess velocity an arc arriving at `vArc` leaves the body with. */
export function excessVelocity(vArc: Vec3, vBody: Vec3): Vec3 {
	return sub(vArc, vBody);
}
