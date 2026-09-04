/**
 * Solve Kepler's equation M = E - e*sin(E) for eccentric anomaly E.
 * Uses Newton-Raphson iteration.
 */
export function solveKepler(M: number, e: number, tolerance = 1e-10, maxIter = 50): number {
	let E = M;
	for (let i = 0; i < maxIter; i++) {
		const dE = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
		// Damp the Newton step: near-parabolic orbits (e ≳ 0.99) with small M
		// have f'(E) = 1 - e·cos(E) ≈ 0, so unclamped steps oscillate chaotically
		// and flicker frame to frame (e.g. Hale-Bopp). Clamping to ≤1 rad keeps
		// quadratic convergence where well-behaved, monotone progress elsewhere.
		const clamped = Math.max(-1, Math.min(1, dE));
		E -= clamped;
		if (Math.abs(dE) < tolerance) break;
	}
	return E;
}

/** sinh overflows past this, so no root beyond it is representable. */
const MAX_H = 700;

/**
 * Solve the hyperbolic Kepler equation M = e*sinh(H) - H for hyperbolic anomaly H.
 * Newton-Raphson kept inside a bracket. Returns NaN when the root is out of range.
 */
export function solveKeplerHyperbolic(
	M: number,
	e: number,
	tolerance = 1e-10,
	maxIter = 50
): number {
	if (M === 0) return 0;
	const sign = M < 0 ? -1 : 1;
	const m = Math.abs(M);
	// f(H) = e·sinh(H) − H − m climbs monotonically from f(0) = −m, so doubling
	// brackets the root. Bare Newton diverges for near-parabolic e: f'(0) = e − 1
	// is ~1e-6, the first step overshoots past H = 100, and the iteration limit
	// hits while H is still ~90 — cosh(90)·a puts the body 1e40 AU out.
	let lo = 0;
	let hi = 1;
	while (e * Math.sinh(hi) - hi < m) {
		hi *= 2;
		if (hi > MAX_H) return NaN;
	}
	let H = 0.5 * (lo + hi);
	for (let i = 0; i < maxIter; i++) {
		const f = e * Math.sinh(H) - H - m;
		if (f > 0) hi = H;
		else lo = H;
		let next = H - f / (e * Math.cosh(H) - 1);
		// Bisect whenever the Newton step leaves the bracket — that is exactly
		// where the flat near-parabolic derivative sends it.
		if (!(next > lo && next < hi)) next = 0.5 * (lo + hi);
		const dH = Math.abs(next - H);
		H = next;
		if (dH < tolerance) break;
	}
	return sign * H;
}

/**
 * Barker's equation for parabolic orbits (e = 1): q [AU], tp [JD] → true
 * anomaly and radius at `jd`, or null on failure.
 * Cubic form W = tan(ν/2)/2 + tan³(ν/2)/6, W = sqrt(GM_sun/(2q³))·(t−tp),
 * GM_sun = k² in AU³/day² (k = 0.01720209895, Gaussian gravitational constant).
 */
export function solveBarker(q: number, tp: number, jd: number): { nu: number; r: number } | null {
	const k = 0.01720209895; // Gaussian gravitational constant [AU^(3/2) / day]
	const dt = jd - tp; // days since perihelion
	const W = (k * dt) / (Math.sqrt(2) * Math.pow(q, 1.5));

	// Barker's formula: cubic solution for s = tan(ν/2) solving 3W = 3s + s³.
	const y = Math.cbrt(3 * W + Math.sqrt(1 + 9 * W * W));
	const s = y - 1 / y; // tan(ν/2)

	const nu = 2 * Math.atan(s);
	const r = q * (1 + s * s); // r = q(1 + tan²(ν/2)) = 2q/(1+cos ν)

	if (!isFinite(nu) || !isFinite(r) || r <= 0) return null;
	return { nu, r };
}
