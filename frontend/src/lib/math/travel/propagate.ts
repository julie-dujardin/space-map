/**
 * Walking a state vector along its own conic.
 *
 * Lambert answers where an arc starts and ends; drawing one needs every point
 * between. That is the universal-variable form of Kepler's equation: one
 * equation covering ellipse, parabola and hyperbola, which matters here because
 * a transfer arc is whatever the dates make it — a fast one crosses e = 1
 * without warning, and two receding comets are joined by a hyperbola.
 *
 * Only the *starting guess* branches on which conic it is, and only because a
 * shared one is not good enough to converge from. Everything after it is the one
 * equation, and a bisection fallback makes the solve total.
 *
 * Curtis §3.7 with Vallado's starters, in km and seconds.
 */

import { add, dot, norm, scale, type Vec3 } from './vec3';

/** Stumpff C(z). The series near zero avoids 0/0 in both branches. */
function stumpffC(z: number): number {
	if (z > 1e-6) {
		const s = Math.sqrt(z);
		return (1 - Math.cos(s)) / z;
	}
	if (z < -1e-6) {
		const s = Math.sqrt(-z);
		return (Math.cosh(s) - 1) / -z;
	}
	return 1 / 2 - z / 24;
}

/** Stumpff S(z). */
function stumpffS(z: number): number {
	if (z > 1e-6) {
		const s = Math.sqrt(z);
		return (s - Math.sin(s)) / (s * s * s);
	}
	if (z < -1e-6) {
		const s = Math.sqrt(-z);
		return (Math.sinh(s) - s) / (s * s * s);
	}
	return 1 / 6 - z / 120;
}

const NEWTON_TOL = 1e-8;
const NEWTON_MAX_ITER = 60;
/** Halvings of the bracket. Sixty takes any of these to the double's precision. */
const BISECTION_STEPS = 60;

/**
 * How far from parabolic an arc has to be before it is treated as one conic or
 * the other, measured as r/a — dimensionless, so it means the same thing for a
 * low orbit and for a comet a thousand AU out. (1/a itself does not: in km it
 * runs around 1e-8 for a planet, so any absolute threshold would call the whole
 * solar system parabolic.)
 */
const PARABOLIC_EPS = 1e-6;

/** Steps the bracket search doubles through before giving up. */
const BRACKET_STEPS = 200;

/**
 * A first guess at χ, per conic.
 *
 * The regimes genuinely need different starters. The elliptic form fed a
 * strongly hyperbolic arc lands an order of magnitude out, and since the
 * hyperbolic Stumpff functions grow like sinh, Newton then steps into a region
 * where the derivative is astronomically large and never comes back.
 */
function startingAnomaly(
	r0: number,
	vr0: number,
	alpha: number,
	dtSec: number,
	mu: number
): number {
	const sqrtMu = Math.sqrt(mu);
	const curvature = r0 * alpha;
	if (curvature > PARABOLIC_EPS) return sqrtMu * alpha * dtSec;

	const sign = dtSec < 0 ? -1 : 1;
	if (curvature < -PARABOLIC_EPS) {
		// Vallado's hyperbolic starter, which inverts the leading exponential term
		// of the hyperbolic Kepler equation instead of its linear one.
		const a = 1 / alpha;
		const ratio =
			(-2 * mu * alpha * dtSec) / (r0 * vr0 + sign * Math.sqrt(-mu * a) * (1 - r0 * alpha));
		if (ratio > 0 && isFinite(ratio)) return sign * Math.sqrt(-a) * Math.log(ratio);
		return sign * Math.sqrt(-a);
	}
	// Near-parabolic: the linear term is all there is to invert. The bracket
	// below does the rest.
	return (sqrtMu * dtSec) / r0;
}

/**
 * The universal anomaly χ reached after `dtSec`, or null if it cannot be found.
 *
 * `alpha` is 1/a — positive on an ellipse, negative on a hyperbola, zero on a
 * parabola — and is what lets one equation serve all three.
 *
 * Newton first, then bisection when it wanders. The fallback is not a
 * consolation prize: dF/dχ is the orbital radius, which is positive everywhere,
 * so F is strictly increasing and its root is unique and always bracketable.
 * That is what makes this total over every conic, which matters because a
 * transfer arc is whatever the dates make it — the arc between two long-period
 * comets is a hyperbola of a = −9 AU, and nothing upstream warns of it.
 */
function universalAnomaly(
	r0: number,
	vr0: number,
	alpha: number,
	dtSec: number,
	mu: number
): number | null {
	const sqrtMu = Math.sqrt(mu);
	const residual = (chi: number): number => {
		const z = alpha * chi * chi;
		const chi2 = chi * chi;
		return (
			(r0 * vr0 * chi2 * stumpffC(z)) / sqrtMu +
			(1 - alpha * r0) * chi2 * chi * stumpffS(z) +
			r0 * chi -
			sqrtMu * dtSec
		);
	};
	const slope = (chi: number): number => {
		const z = alpha * chi * chi;
		return (
			(r0 * vr0 * chi * (1 - z * stumpffS(z))) / sqrtMu +
			(1 - alpha * r0) * chi * chi * stumpffC(z) +
			r0
		);
	};

	let chi = startingAnomaly(r0, vr0, alpha, dtSec, mu);
	if (isFinite(chi)) {
		for (let i = 0; i < NEWTON_MAX_ITER; i++) {
			const f = residual(chi);
			const df = slope(chi);
			if (!isFinite(f) || !isFinite(df) || df === 0) break;
			const step = f / df;
			chi -= step;
			if (!isFinite(chi)) break;
			if (Math.abs(step) < NEWTON_TOL * Math.max(1, Math.abs(chi))) return chi;
		}
	}

	// Bracket outward from zero, where the residual has the sign of −dt, then
	// halve. The guess above is only a scale hint here.
	const sign = dtSec < 0 ? -1 : 1;
	let hi = Math.abs(isFinite(chi) && chi !== 0 ? chi : 1) * sign;
	let lo = 0;
	let bracketed = false;
	for (let i = 0; i < BRACKET_STEPS; i++) {
		const f = residual(hi);
		if (!isFinite(f)) return null;
		if (f * sign >= 0) {
			bracketed = true;
			break;
		}
		lo = hi;
		hi *= 2;
		if (!isFinite(hi)) return null;
	}
	if (!bracketed) return null;

	for (let i = 0; i < BISECTION_STEPS; i++) {
		const mid = (lo + hi) / 2;
		const f = residual(mid);
		if (!isFinite(f)) return null;
		if (f * sign >= 0) hi = mid;
		else lo = mid;
	}
	return (lo + hi) / 2;
}

/**
 * Where a body at `r`/`v` is `dtSec` later on the same two-body arc, and how
 * fast it is going when it gets there. Km and km/s.
 *
 * `dtSec` may be negative, which walks the arc backwards. Returns null when the
 * state is degenerate or the iteration diverges — a caller drawing a path
 * should drop the sample rather than draw a NaN.
 */
export function propagateFull(
	r: Vec3,
	v: Vec3,
	dtSec: number,
	mu: number
): { r: Vec3; v: Vec3 } | null {
	if (!(mu > 0)) return null;
	const r0 = norm(r);
	if (!(r0 > 0)) return null;
	if (dtSec === 0) return { r, v };

	const v2 = dot(v, v);
	const vr0 = dot(r, v) / r0;
	const alpha = 2 / r0 - v2 / mu;

	const chi = universalAnomaly(r0, vr0, alpha, dtSec, mu);
	if (chi === null) return null;

	const z = alpha * chi * chi;
	// Lagrange coefficients: the new state is a combination of the old position
	// and velocity, so no frame or element set is ever built.
	const f = 1 - (chi * chi * stumpffC(z)) / r0;
	const g = dtSec - (chi * chi * chi * stumpffS(z)) / Math.sqrt(mu);
	if (!isFinite(f) || !isFinite(g)) return null;

	const rNext = add(scale(r, f), scale(v, g));
	const rNextNorm = norm(rNext);
	if (!isFinite(rNextNorm) || !(rNextNorm > 0)) return null;

	// The rates of the same two coefficients, which need the new radius — so the
	// velocity cannot be had without the position first.
	const fDot = (Math.sqrt(mu) / (r0 * rNextNorm)) * (z * stumpffS(z) - 1) * chi;
	const gDot = 1 - (chi * chi * stumpffC(z)) / rNextNorm;
	if (!isFinite(fDot) || !isFinite(gDot)) return null;

	const vNext = add(scale(r, fDot), scale(v, gDot));
	return isFinite(vNext[0] + vNext[1] + vNext[2]) ? { r: rNext, v: vNext } : null;
}

/** Where a body at `r`/`v` is `dtSec` later on the same two-body arc, km. */
export function propagateState(r: Vec3, v: Vec3, dtSec: number, mu: number): Vec3 | null {
	return propagateFull(r, v, dtSec, mu)?.r ?? null;
}
