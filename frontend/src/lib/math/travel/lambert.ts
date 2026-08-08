/**
 * Lambert's problem — the two-body arc joining two positions in a given time.
 *
 * Izzo's 2014 formulation, the same one pykep and poliastro use. It reduces the
 * problem to a single scalar `x` and converges in a handful of Householder
 * steps with no bracketing, which is what makes a porkchop grid of tens of
 * thousands of solves cheap enough to run per-interaction.
 *
 * Only the zero-revolution branch is implemented. Multi-revolution transfers
 * exist for long times of flight and can beat the direct arc; callers that grid
 * out multi-year windows should treat the result as an upper bound on cost.
 */

import type { Vec3 } from './vec3';
import { cross, dot, norm, normalize, scale, sub } from './vec3';

export interface LambertArc {
	/** Velocity at `r1` on the transfer arc, km/s. */
	v1: Vec3;
	/** Velocity at `r2` on the transfer arc, km/s. */
	v2: Vec3;
}

const HOUSEHOLDER_TOL = 1e-11;
const HOUSEHOLDER_MAX_ITER = 15;

/**
 * Solve for the arc from `r1` to `r2` in `tofSec`.
 *
 * Positions are in km in any consistent inertial frame; `mu` in km³/s².
 * `retrograde` picks the transfer that runs clockwise about the frame's +Z
 * axis — for heliocentric transfers in ecliptic J2000 the default (prograde) is
 * what you want, since the planets all orbit that way.
 *
 * Returns null for degenerate geometry: coincident or antipodal endpoints
 * (where the transfer plane is undefined), non-positive time of flight, or a
 * non-converged solve.
 */
export function solveLambert(
	r1: Vec3,
	r2: Vec3,
	tofSec: number,
	mu: number,
	retrograde = false
): LambertArc | null {
	if (!(tofSec > 0) || !(mu > 0)) return null;

	const r1n = norm(r1);
	const r2n = norm(r2);
	if (!(r1n > 0) || !(r2n > 0)) return null;

	const chord = sub(r2, r1);
	const c = norm(chord);
	const s = (r1n + r2n + c) / 2;
	if (!(s > 0) || c === 0) return null;

	const ir1 = normalize(r1);
	const ir2 = normalize(r2);
	const h = cross(ir1, ir2);
	const hn = norm(h);
	// Collinear endpoints (transfer angle 0 or π) leave the plane undefined.
	if (hn < 1e-12) return null;
	const ih = scale(h, 1 / hn);

	const lambda2 = 1 - c / s;
	if (lambda2 < 0) return null;
	let lambda = Math.sqrt(lambda2);

	let it1: Vec3;
	let it2: Vec3;
	if (ih[2] < 0) {
		// Transfer angle exceeds π when measured prograde about +Z.
		lambda = -lambda;
		it1 = cross(ir1, ih);
		it2 = cross(ir2, ih);
	} else {
		it1 = cross(ih, ir1);
		it2 = cross(ih, ir2);
	}
	it1 = normalize(it1);
	it2 = normalize(it2);

	if (retrograde) {
		lambda = -lambda;
		it1 = scale(it1, -1);
		it2 = scale(it2, -1);
	}

	// Non-dimensional time of flight.
	const T = Math.sqrt((2 * mu) / (s * s * s)) * tofSec;
	if (!isFinite(T)) return null;

	const x = solveForX(T, lambda);
	if (x === null) return null;

	const lambdaSq = lambda * lambda;
	const y = Math.sqrt(1 - lambdaSq * (1 - x * x));
	const gamma = Math.sqrt((mu * s) / 2);
	const rho = (r1n - r2n) / c;
	const sigma = Math.sqrt(Math.max(0, 1 - rho * rho));

	const vr1 = (gamma * (lambda * y - x - rho * (lambda * y + x))) / r1n;
	const vr2 = (-gamma * (lambda * y - x + rho * (lambda * y + x))) / r2n;
	const vt = gamma * sigma * (y + lambda * x);

	const v1: Vec3 = [
		vr1 * ir1[0] + (vt / r1n) * it1[0],
		vr1 * ir1[1] + (vt / r1n) * it1[1],
		vr1 * ir1[2] + (vt / r1n) * it1[2]
	];
	const v2: Vec3 = [
		vr2 * ir2[0] + (vt / r2n) * it2[0],
		vr2 * ir2[1] + (vt / r2n) * it2[1],
		vr2 * ir2[2] + (vt / r2n) * it2[2]
	];

	if (!isFinite(dot(v1, v1)) || !isFinite(dot(v2, v2))) return null;
	return { v1, v2 };
}

/** Householder iteration on the non-dimensional time-of-flight curve. */
function solveForX(T: number, lambda: number): number | null {
	const lambda2 = lambda * lambda;
	const lambda3 = lambda2 * lambda;

	// Izzo's zero-revolution initial guess, piecewise in the three regimes
	// bounded by the parabolic (T1) and minimum-energy (T0) times.
	const T0 = Math.acos(lambda) + lambda * Math.sqrt(1 - lambda2);
	const T1 = (2 / 3) * (1 - lambda3);
	let x: number;
	if (T >= T0) {
		x = -(T - T0) / (T - T0 + 4);
	} else if (T <= T1) {
		x = (T1 * (T1 - T)) / ((2 / 5) * (1 - lambda2 * lambda3) * T) + 1;
	} else {
		x = Math.pow(T / T0, Math.log(2) / Math.log(T1 / T0)) - 1;
	}

	for (let iter = 0; iter < HOUSEHOLDER_MAX_ITER; iter++) {
		const tof = timeOfFlight(x, lambda);
		if (!isFinite(tof)) return null;
		const delta = tof - T;

		const umx2 = 1 - x * x;
		const y = Math.sqrt(1 - lambda2 * umx2);
		const y3 = y * y * y;
		const dT = (3 * tof * x - 2 + (2 * lambda3 * x) / y) / umx2;
		const ddT = (3 * tof + 5 * x * dT + (2 * (1 - lambda2) * lambda3) / y3) / umx2;
		const dddT =
			(7 * x * ddT + 8 * dT - (6 * (1 - lambda2) * lambda2 * lambda3 * x) / (y3 * y * y)) / umx2;

		const dT2 = dT * dT;
		const denom = dT * (dT2 - delta * ddT) + (dddT * delta * delta) / 6;
		if (denom === 0 || !isFinite(denom)) return null;
		const xNew = x - (delta * (dT2 - (delta * ddT) / 2)) / denom;
		if (!isFinite(xNew)) return null;

		const err = Math.abs(x - xNew);
		x = xNew;
		if (err < HOUSEHOLDER_TOL) return x;
	}
	// Householder is cubic here; not converging in 15 steps means the geometry
	// is degenerate rather than merely slow.
	return null;
}

/**
 * Non-dimensional time of flight for a given `x`.
 *
 * Three expressions cover the domain: a Battin series next to the parabolic
 * point x = 1, Lagrange's closed form just outside it, and Lancaster's form
 * elsewhere. The switch exists because each loses precision where the others
 * hold — near x = 1 the Lancaster denominator (x² − 1) vanishes.
 */
function timeOfFlight(x: number, lambda: number): number {
	const BATTIN = 0.01;
	const LAGRANGE = 0.2;
	const dist = Math.abs(x - 1);

	if (dist < LAGRANGE && dist > BATTIN) return lagrangeTof(x, lambda);

	const lambda2 = lambda * lambda;
	const E = x * x - 1;
	const rho = Math.abs(E);
	const z = Math.sqrt(1 + lambda2 * E);

	if (dist < BATTIN) {
		const eta = z - lambda * x;
		const S1 = 0.5 * (1 - lambda - x * eta);
		const Q = (4 / 3) * hypergeometric2F1(S1);
		return (eta * eta * eta * Q + 4 * lambda * eta) / 2;
	}

	const y = Math.sqrt(rho);
	const g = x * z - lambda * E;
	let d: number;
	if (E < 0) {
		d = Math.acos(Math.max(-1, Math.min(1, g)));
	} else {
		d = Math.log(y * (z - lambda * x) + g);
	}
	return (x - lambda * z - d / y) / E;
}

/** Lagrange's form, valid on both the elliptic and hyperbolic sides. */
function lagrangeTof(x: number, lambda: number): number {
	const a = 1 / (1 - x * x);
	const lambda2 = lambda * lambda;
	if (a > 0) {
		const alpha = 2 * Math.acos(Math.max(-1, Math.min(1, x)));
		let beta = 2 * Math.asin(Math.sqrt(Math.max(0, lambda2 / a)));
		if (lambda < 0) beta = -beta;
		return (a * Math.sqrt(a) * (alpha - Math.sin(alpha) - (beta - Math.sin(beta)))) / 2;
	}
	const alpha = 2 * Math.acosh(x);
	let beta = 2 * Math.asinh(Math.sqrt(-lambda2 / a));
	if (lambda < 0) beta = -beta;
	return (-a * Math.sqrt(-a) * (beta - Math.sinh(beta) - (alpha - Math.sinh(alpha)))) / 2;
}

/** ₂F₁(3, 1; 5/2; z) by its series, which converges fast for the |z| < 1 here. */
function hypergeometric2F1(z: number, tol = 1e-11): number {
	let sum = 1;
	let term = 1;
	for (let j = 0; j < 200; j++) {
		term = (term * ((3 + j) * (1 + j))) / (2.5 + j) / (j + 1);
		term *= z;
		sum += term;
		if (Math.abs(term) < tol) break;
	}
	return sum;
}
