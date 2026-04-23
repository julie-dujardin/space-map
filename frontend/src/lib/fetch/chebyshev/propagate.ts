/**
 * Evaluate parent-relative position from Chebyshev polynomial segments.
 *
 * Coefficients are in km in the ECLIPJ2000 ecliptic frame (numpy convention:
 * `c[0]·T_0 + c[1]·T_1 + … + c[N-1]·T_{N-1}`); `kmToScene` + axis swap maps
 * to the Three.js basis the rest of the scene uses.
 */

import { kmToScene } from '$lib/math/units';
import type { ChebyshevBody } from '$lib/fetch/chebyshev/parse';

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
