/**
 * Evaluate parent-relative probe position from a parsed `ProbeChunk`.
 *
 * Dispatches per sub-chunk on the method byte:
 *   - kepler_pure  : 6 elements + anchor offset; M drifts at sqrt(mu/a³) from t_anchor
 *   - kepler_drift : 6 elements + fitted Ω̇/ω̇/ṅ; M, om, w drift linearly from t_anchor
 *   - chebyshev    : Clenshaw recurrence over per-segment coefficients
 *   - uncoverable  : returns null (consumer hides the probe)
 *
 * Units throughout: positions in km, ECLIPJ2000 frame, parent-relative (parent =
 * the zone's `fit_center_naif_id` body); times in ET seconds past J2000.
 * `kmToScene` + axis swap maps to the Three.js basis the rest of the scene uses.
 *
 * `mu` is the gravitational parameter (km³/s²) of the zone's fit center, looked
 * up by the caller via `getGmKm3s2(fit_center_naif_id)`.
 */

import { kmToScene } from '$lib/math/units';
import { solveKepler } from '$lib/math/orbit/solvers';
import {
	PROBE_METHOD_CHEBYSHEV,
	PROBE_METHOD_KEPLER_DRIFT,
	PROBE_METHOD_KEPLER_PURE,
	PROBE_METHOD_UNCOVERABLE
} from '$lib/fetch/position/format';
import type {
	ChebyshevSub,
	KeplerDriftElts,
	KeplerPureElts,
	Probe,
	SubChunk
} from '$lib/fetch/position/probes/parse';

const SECONDS_PER_DAY = 86400;
const JD_J2000 = 2451545.0;

/** JD (TDB) → seconds past J2000. Shared with the parser; defined here too so
 *  callers don't have to thread the parser's private helper through. */
export function jdToEt(jd: number): number {
	return (jd - JD_J2000) * SECONDS_PER_DAY;
}

/** Binary search for the largest `i` with `subStartEt[i] <= et < subEndEt[i]`,
 *  or -1 when `et` falls outside the probe's covered range. Assumes sub-chunks
 *  are contiguous and time-sorted (writer guarantees this). */
export function findSubChunkIndex(probe: Probe, et: number): number {
	const starts = probe.subStartEt;
	const ends = probe.subEndEt;
	const n = starts.length;
	if (n === 0 || et < starts[0] || et >= ends[n - 1]) return -1;
	let lo = 0;
	let hi = n - 1;
	while (lo < hi) {
		const mid = (lo + hi + 1) >>> 1;
		if (starts[mid] <= et) lo = mid;
		else hi = mid - 1;
	}
	return et < ends[lo] ? lo : -1;
}

/** Rotate a vector in the orbital plane (z=0) to ECLIPJ2000 by the standard
 *  R_z(om) · R_x(i) · R_z(w) sequence. Angles in radians, lengths preserved. */
function orbitalPlaneToEclip(
	xOrb: number,
	yOrb: number,
	om: number,
	i: number,
	w: number
): [number, number, number] {
	const cosW = Math.cos(w);
	const sinW = Math.sin(w);
	const cosI = Math.cos(i);
	const sinI = Math.sin(i);
	const cosOm = Math.cos(om);
	const sinOm = Math.sin(om);
	const x =
		(cosOm * cosW - sinOm * sinW * cosI) * xOrb + (-cosOm * sinW - sinOm * cosW * cosI) * yOrb;
	const y =
		(sinOm * cosW + cosOm * sinW * cosI) * xOrb + (-sinOm * sinW + cosOm * cosW * cosI) * yOrb;
	const z = sinW * sinI * xOrb + cosW * sinI * yOrb;
	return [x, y, z];
}

/** Solve an osculating-element Kepler orbit at mean anomaly `M` (rad). Returns
 *  ECLIPJ2000 km. Mirrors `spiceypy.conics` for the elliptic-orbit path the
 *  writer fits against. */
function keplerOrbitalPositionKm(
	aKm: number,
	e: number,
	iRad: number,
	om: number,
	w: number,
	M: number
): [number, number, number] | null {
	// The writer's fit rejects sub-chunks that go hyperbolic, so this branch
	// is the only one we need; if a fit ever ships e ≥ 1 we'll see it in the
	// finite-check below and hide the probe rather than diverge.
	if (e >= 1) return null;
	const E = solveKepler(M, e);
	const sinE = Math.sin(E);
	const cosE = Math.cos(E);
	const sinNu = (Math.sqrt(1 - e * e) * sinE) / (1 - e * cosE);
	const cosNu = (cosE - e) / (1 - e * cosE);
	const r = aKm * (1 - e * cosE);
	const xOrb = r * cosNu;
	const yOrb = r * sinNu;
	if (!isFinite(xOrb) || !isFinite(yOrb)) return null;
	return orbitalPlaneToEclip(xOrb, yOrb, om, iRad, w);
}

function keplerPurePosition(
	sub: KeplerPureElts,
	subStartEt: number,
	et: number,
	muKm3S2: number
): [number, number, number] | null {
	const tAnchorEt = subStartEt + sub.tAnchorOffsetS;
	const dtS = et - tAnchorEt;
	const n = Math.sqrt(muKm3S2 / (sub.aKm * sub.aKm * sub.aKm));
	const M = sub.m0 + n * dtS;
	return keplerOrbitalPositionKm(sub.aKm, sub.e, sub.iRad, sub.om0, sub.w0, M);
}

function keplerDriftPosition(
	sub: KeplerDriftElts,
	subStartEt: number,
	et: number
): [number, number, number] | null {
	const tAnchorEt = subStartEt + sub.tAnchorOffsetS;
	const dtS = et - tAnchorEt;
	const om = sub.om0 + sub.omDot * dtS;
	const w = sub.w0 + sub.wDot * dtS;
	const M = sub.m0 + sub.nMeanRadS * dtS;
	return keplerOrbitalPositionKm(sub.aKm, sub.e, sub.iRad, om, w, M);
}

function chebyshevPosition(
	sub: ChebyshevSub,
	subStartEt: number,
	subEndEt: number,
	et: number
): [number, number, number] | null {
	const { coeffs, coeffsPerAxis: N, nSeg } = sub;
	const segDt = (subEndEt - subStartEt) / nSeg;
	let seg = Math.floor((et - subStartEt) / segDt);
	if (seg < 0) seg = 0;
	else if (seg >= nSeg) seg = nSeg - 1;
	const segStart = subStartEt + seg * segDt;
	const tau = (2 * (et - segStart)) / segDt - 1;
	const twoTau = 2 * tau;
	const base = seg * 3 * N;
	const out: [number, number, number] = [0, 0, 0];
	for (let axis = 0; axis < 3; axis++) {
		const aBase = base + axis * N;
		if (N === 1) {
			out[axis] = coeffs[aBase];
			continue;
		}
		let bkp1 = 0;
		let bkp2 = 0;
		for (let k = N - 1; k >= 1; k--) {
			const bk = coeffs[aBase + k] + twoTau * bkp1 - bkp2;
			bkp2 = bkp1;
			bkp1 = bk;
		}
		out[axis] = coeffs[aBase] + tau * bkp1 - bkp2;
	}
	if (!isFinite(out[0]) || !isFinite(out[1]) || !isFinite(out[2])) return null;
	return out;
}

function evalSubChunk(
	sub: SubChunk,
	subStartEt: number,
	subEndEt: number,
	et: number,
	muKm3S2: number
): [number, number, number] | null {
	switch (sub.method) {
		case PROBE_METHOD_UNCOVERABLE:
			return null;
		case PROBE_METHOD_KEPLER_PURE:
			return keplerPurePosition(sub, subStartEt, et, muKm3S2);
		case PROBE_METHOD_KEPLER_DRIFT:
			return keplerDriftPosition(sub, subStartEt, et);
		case PROBE_METHOD_CHEBYSHEV:
			return chebyshevPosition(sub, subStartEt, subEndEt, et);
	}
}

/**
 * Parent-relative probe position in km at `jd` (TDB). Returns null when the
 * probe has no sub-chunk covering `jd`, or the sub-chunk is uncoverable, or
 * the underlying fit produced a non-finite value.
 *
 * `muKm3S2` is the GM of the zone's `fit_center_naif_id` body. Pass 0 to
 * disable Kepler-pure evaluation explicitly — callers that don't have the GM
 * yet should drop the body for the frame rather than call this with junk.
 */
export function probePositionKm(
	probe: Probe,
	jd: number,
	muKm3S2: number
): [number, number, number] | null {
	const et = jdToEt(jd);
	const idx = findSubChunkIndex(probe, et);
	if (idx < 0) return null;
	return evalSubChunk(
		probe.subChunks[idx],
		probe.subStartEt[idx],
		probe.subEndEt[idx],
		et,
		muKm3S2
	);
}

/** Parent-relative probe position in Three.js scene units. Same axis swap as
 *  the chebyshev path: ecliptic X→X, ecliptic Z→Y, ecliptic Y→−Z. */
export function probePositionScene(
	probe: Probe,
	jd: number,
	muKm3S2: number
): [number, number, number] | null {
	const km = probePositionKm(probe, jd, muKm3S2);
	if (km === null) return null;
	return [kmToScene(km[0]), kmToScene(km[2]), -kmToScene(km[1])];
}

const VELOCITY_FD_HALF_WINDOW_S = 30;
const VELOCITY_FD_HALF_WINDOW_JD = VELOCITY_FD_HALF_WINDOW_S / SECONDS_PER_DAY;

/**
 * Parent-relative probe state (km, km/day) at `jd` via centered finite
 * difference of {@link probePositionKm}. Method-agnostic — handles Kepler-pure,
 * Kepler-drift, and Chebyshev sub-chunks uniformly. Velocity units match
 * {@link chebyshevStateKm} so downstream conversions to AU/day are shared.
 *
 * Returns null when any of the three samples is null (e.g. the ±30 s window
 * crosses the probe's coverage boundary or both sides fall in an uncoverable
 * sub-chunk). Callers fall back to a position-only entry in that case.
 */
export function probeStateKm(
	probe: Probe,
	jd: number,
	muKm3S2: number
): { position: [number, number, number]; velocity: [number, number, number] } | null {
	const center = probePositionKm(probe, jd, muKm3S2);
	if (center === null) return null;
	const plus = probePositionKm(probe, jd + VELOCITY_FD_HALF_WINDOW_JD, muKm3S2);
	const minus = probePositionKm(probe, jd - VELOCITY_FD_HALF_WINDOW_JD, muKm3S2);
	if (plus === null || minus === null) return null;
	const inv2dt = 1 / (2 * VELOCITY_FD_HALF_WINDOW_JD); // km/day per km
	return {
		position: center,
		velocity: [
			(plus[0] - minus[0]) * inv2dt,
			(plus[1] - minus[1]) * inv2dt,
			(plus[2] - minus[2]) * inv2dt
		]
	};
}
