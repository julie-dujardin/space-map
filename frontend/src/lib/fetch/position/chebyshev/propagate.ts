/**
 * Evaluate parent-relative position from Chebyshev polynomial segments.
 *
 * Coefficients are in km in the ECLIPJ2000 ecliptic frame (numpy convention:
 * `c[0]·T_0 + c[1]·T_1 + … + c[N-1]·T_{N-1}`); `kmToScene` + axis swap maps
 * to the Three.js basis the rest of the scene uses.
 */

import { kmToScene } from '$lib/math/units';
import type { ChebyshevBody } from '$lib/fetch/position/chebyshev/parse';

/**
 * Largest `i` with `starts[i] <= jd < ends[i]`, or -1 if `jd` falls outside the
 * body's covered range. Assumes segments are sorted and contiguous (as the
 * Python writer produces).
 */
function findSegmentIndex(starts: Float64Array, ends: Float64Array, jd: number): number {
	const n = starts.length;
	if (n === 0 || jd < starts[0] || jd >= ends[n - 1]) return -1;

	let lo = 0;
	let hi = n - 1;
	while (lo < hi) {
		const mid = (lo + hi + 1) >>> 1;
		if (starts[mid] <= jd) lo = mid;
		else hi = mid - 1;
	}
	return jd < ends[lo] ? lo : -1;
}

/**
 * Evaluate the body's parent-relative position at `jd` in kilometres, ECLIPJ2000.
 * Returns null when `jd` is outside the covered segment range.
 */
export function chebyshevPositionKm(
	body: ChebyshevBody,
	jd: number
): [number, number, number] | null {
	const idx = findSegmentIndex(body.startJds, body.endJds, jd);
	if (idx < 0) return null;

	const start = body.startJds[idx];
	const end = body.endJds[idx];
	// Map JD in [start, end] onto τ in [-1, 1] (the Chebyshev domain).
	const tau = (2 * (jd - start)) / (end - start) - 1;

	const N = body.coeffsPerAxis;
	const coeffs = body.coeffs;
	const base = idx * 3 * N;
	const result: [number, number, number] = [0, 0, 0];
	const twoTau = 2 * tau;

	// Clenshaw recurrence for Chebyshev T_n:
	//   b_{N} = 0, b_{N+1} = 0
	//   b_k = c_k + 2τ·b_{k+1} - b_{k+2}  for k = N-1..1
	//   result = c_0 + τ·b_1 - b_2
	for (let axis = 0; axis < 3; axis++) {
		const aBase = base + axis * N;
		if (N === 1) {
			result[axis] = coeffs[aBase];
			continue;
		}
		let bkp1 = 0;
		let bkp2 = 0;
		for (let k = N - 1; k >= 1; k--) {
			const bk = coeffs[aBase + k] + twoTau * bkp1 - bkp2;
			bkp2 = bkp1;
			bkp1 = bk;
		}
		result[axis] = coeffs[aBase] + tau * bkp1 - bkp2;
	}

	return result;
}

/**
 * Parent-relative position in Three.js scene units.
 *
 * Scene convention: ecliptic X→X, ecliptic Z (north)→Y, ecliptic Y→−Z; matches
 * the orbital-elements path in [$lib/math/orbit/position.ts].
 */
export function chebyshevPositionScene(
	body: ChebyshevBody,
	jd: number
): [number, number, number] | null {
	const km = chebyshevPositionKm(body, jd);
	if (km === null) return null;
	return [kmToScene(km[0]), kmToScene(km[2]), -kmToScene(km[1])];
}

/**
 * Parent-relative state vector at `jd`: position (km) and velocity (km/day) in
 * ECLIPJ2000. Returns null when `jd` is outside the body's segment coverage.
 *
 * Velocity is the analytic derivative of the Chebyshev sum:
 *   P(τ) = Σ c_k T_k(τ),  P'(τ) = Σ c_k k U_{k−1}(τ),  dτ/dt = 2 / (end − start).
 * The U_n sum is evaluated by Clenshaw on the modified coefficients d_j =
 * c_{j+1}(j+1), exploiting that U_n shares the recurrence U_n = 2τU_{n−1} − U_{n−2}
 * with T_n (just different initial values, hence S = b_0 instead of T's
 * c_0 + τb_1 − b_2).
 */
export function chebyshevStateKm(
	body: ChebyshevBody,
	jd: number
): { position: [number, number, number]; velocity: [number, number, number] } | null {
	const idx = findSegmentIndex(body.startJds, body.endJds, jd);
	if (idx < 0) return null;

	const start = body.startJds[idx];
	const end = body.endJds[idx];
	const tau = (2 * (jd - start)) / (end - start) - 1;
	const dTauDt = 2 / (end - start);

	const N = body.coeffsPerAxis;
	const coeffs = body.coeffs;
	const base = idx * 3 * N;
	const position: [number, number, number] = [0, 0, 0];
	const velocity: [number, number, number] = [0, 0, 0];
	const twoTau = 2 * tau;

	for (let axis = 0; axis < 3; axis++) {
		const aBase = base + axis * N;
		if (N === 1) {
			position[axis] = coeffs[aBase];
			velocity[axis] = 0;
			continue;
		}

		// Position via standard T_n Clenshaw.
		let bkp1 = 0;
		let bkp2 = 0;
		for (let k = N - 1; k >= 1; k--) {
			const bk = coeffs[aBase + k] + twoTau * bkp1 - bkp2;
			bkp2 = bkp1;
			bkp1 = bk;
		}
		position[axis] = coeffs[aBase] + tau * bkp1 - bkp2;

		// Velocity via U_n Clenshaw with d_j = c_{j+1}(j+1) for j = 0..N-2.
		let dkp1 = 0;
		let dkp2 = 0;
		for (let j = N - 2; j >= 0; j--) {
			const dj = coeffs[aBase + j + 1] * (j + 1);
			const dk = dj + twoTau * dkp1 - dkp2;
			dkp2 = dkp1;
			dkp1 = dk;
		}
		velocity[axis] = dkp1 * dTauDt;
	}

	return { position, velocity };
}
