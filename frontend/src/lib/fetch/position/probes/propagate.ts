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
	LandedRecord,
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

/** True iff a probe has a landed record active at `jd` — the renderer uses
 *  this to dispatch between the flying and landed branches. */
export function isLandedAt(probe: Probe, jd: number): boolean {
	if (!probe.landed) return false;
	const et = jdToEt(jd);
	return et >= probe.landed.startEt && et < probe.landed.endEt;
}

/** Stair-step lookup into a `LandedRecord`: returns the (lat°, lon°, alt m)
 *  of the latest sample whose et ≤ now, or the reference position for
 *  static phases / pre-first-sample times. Returns null when `jd` is
 *  outside the landed window — caller falls back to the flying path. */
export function landedPositionAt(
	landed: LandedRecord,
	jd: number
): { latDeg: number; lngDeg: number; altM: number } | null {
	const et = jdToEt(jd);
	if (et < landed.startEt || et >= landed.endEt) return null;
	const n = landed.sampleEt.length;
	if (n === 0 || et < landed.sampleEt[0]) {
		return { latDeg: landed.latRefDeg, lngDeg: landed.lngRefDeg, altM: landed.altRefM };
	}
	// Binary search for largest i with sampleEt[i] ≤ et — stair-step (the rover
	// sat at sample i's position until sample i+1's et).
	let lo = 0;
	let hi = n - 1;
	while (lo < hi) {
		const mid = (lo + hi + 1) >>> 1;
		if (landed.sampleEt[mid] <= et) lo = mid;
		else hi = mid - 1;
	}
	return {
		latDeg: landed.sampleLatDeg[lo],
		lngDeg: landed.sampleLngDeg[lo],
		altM: landed.sampleAltM[lo]
	};
}

const VELOCITY_FD_HALF_WINDOW_S = 30;
const VELOCITY_FD_HALF_WINDOW_JD = VELOCITY_FD_HALF_WINDOW_S / SECONDS_PER_DAY;

/**
 * Parent-relative probe state (km, km/day) at `jd` via finite difference of
 * {@link probePositionKm}. Method-agnostic — handles Kepler-pure, Kepler-drift,
 * and Chebyshev sub-chunks uniformly. Velocity units match {@link chebyshevStateKm}
 * so downstream conversions to AU/day are shared.
 *
 * Prefers a centered FD (second-order accuracy). At the very first / very last
 * sub-chunk's boundary one side of the window falls outside any sub-chunk —
 * NH's interplanetary chunk 64 has its first sub-chunk start snapped to
 * 2014-12-10 00:00 because the kernel only opens at 2014-12-08 05:12, so jd-30s
 * has no sub-chunk to evaluate against. In that case fall back to a one-sided
 * forward / backward FD (first-order) so the osculating element derivation
 * still works at coverage edges instead of leaving the drawer empty.
 *
 * Returns null only when the center sample itself misses (jd outside coverage)
 * or when both side samples miss (a sub-chunk so short it's smaller than the
 * FD window on both sides — should never happen with the writer's 7-day
 * minimum interplanetary sub-chunks).
 */
export function probeStateKm(
	probe: Probe,
	jd: number,
	muKm3S2: number
): { position: [number, number, number]; velocity: [number, number, number] } | null {
	const center = probePositionKm(probe, jd, muKm3S2);
	if (center === null) return null;
	const dt = VELOCITY_FD_HALF_WINDOW_JD;
	const plus = probePositionKm(probe, jd + dt, muKm3S2);
	const minus = probePositionKm(probe, jd - dt, muKm3S2);
	let a: [number, number, number];
	let b: [number, number, number];
	let invDt: number;
	if (plus !== null && minus !== null) {
		a = plus;
		b = minus;
		invDt = 1 / (2 * dt);
	} else if (plus !== null) {
		a = plus;
		b = center;
		invDt = 1 / dt;
	} else if (minus !== null) {
		a = center;
		b = minus;
		invDt = 1 / dt;
	} else {
		return null;
	}
	return {
		position: center,
		velocity: [(a[0] - b[0]) * invDt, (a[1] - b[1]) * invDt, (a[2] - b[2]) * invDt]
	};
}
