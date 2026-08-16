/**
 * Solve Kepler's equation M = E - e*sin(E) for eccentric anomaly E.
 * Uses Newton-Raphson iteration.
 */
export function solveKepler(M: number, e: number, tolerance = 1e-10, maxIter = 50): number {
	let E = M;
	for (let i = 0; i < maxIter; i++) {
		const dE = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
		// Damp the Newton step. For near-parabolic orbits (e ≳ 0.99) with small
		// M, f'(E) = 1 - e·cos(E) is near zero and unclamped Newton-Raphson
		// shoots past the solution and can oscillate chaotically — stopping at
		// different E each frame causes visible position flicker (e.g. Hale-Bopp).
		// Clamping each step to ≤1 rad preserves quadratic convergence where
		// it's well-behaved and forces monotone progress elsewhere.
		const clamped = Math.max(-1, Math.min(1, dE));
		E -= clamped;
		if (Math.abs(dE) < tolerance) break;
	}
	return E;
}

/**
 * Solve the hyperbolic Kepler equation M = e*sinh(H) - H for hyperbolic anomaly H.
 * Uses Newton-Raphson iteration.
 * Returns NaN if the solver fails to converge or overflows.
 */
export function solveKeplerHyperbolic(
	M: number,
	e: number,
	tolerance = 1e-10,
	maxIter = 50
): number {
	let H = Math.abs(M) < 1 ? M : Math.sign(M) * Math.log((2 * Math.abs(M)) / e);
	for (let i = 0; i < maxIter; i++) {
		const sH = Math.sinh(H);
		const cH = Math.cosh(H);
		if (!isFinite(sH) || !isFinite(cH)) return NaN;
		const dH = (e * sH - H - M) / (e * cH - 1);
		H -= dH;
		if (Math.abs(dH) < tolerance) break;
	}
	return H;
}

/**
 * Solve Barker's equation for parabolic orbits (e = 1).
 *
 * Given perihelion distance q [AU] and time of perihelion tp [JD],
 * returns [trueAnomaly, radius] at the given Julian date, or null
 * if the computation fails.
 *
 * Uses the standard cubic form:  W = tan(ν/2)/2 + tan³(ν/2)/6
 * where W = sqrt(GM_sun / (2 q³)) · (t − tp),
 * with GM_sun in AU³/day² = k² (k = 0.01720209895 rad/day, Gaussian gravitational constant).
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
