/**
 * Osculating Keplerian elements from a probe's currently-active sub-chunk.
 *
 * Maps each probe propagation method to the orbit-line refresh path it shares
 * with the rest of the scene:
 *   - kepler_pure  → static OrbitalElements (no drift). Re-derive across
 *                    sub-chunk boundaries picks up the next sub-chunk's
 *                    elements automatically.
 *   - kepler_drift → OrbitalElements + omDot/wDot in deg/day. Hits the existing
 *                    Method-C drift gate in `refreshOrbitLineGeometry`.
 *   - chebyshev    → osculating elements from a state-vector sample (mirrors
 *                    `chebyshevOsculatingElements` in chunk.ts).
 *   - uncoverable  → null; orbit line is skipped.
 *
 * Returns null when `mu <= 0` for the Kepler paths (no mean motion can be
 * derived) or when the chebyshev state sample is null / degenerate.
 */

import type { OrbitalElements } from '$lib/types/objects';
import { AU_KM, KM3_S2_TO_AU3_DAY2 } from '$lib/math/units';
import { stateVectorToElements } from '$lib/math/orbit/state';
import {
	PROBE_METHOD_CHEBYSHEV,
	PROBE_METHOD_KEPLER_DRIFT,
	PROBE_METHOD_KEPLER_PURE,
	PROBE_METHOD_UNCOVERABLE
} from '$lib/fetch/position/format';
import type { KeplerDriftElts, KeplerPureElts, Probe } from '$lib/fetch/position/probes/parse';
import { findSubChunkIndex, jdToEt, probeStateKm } from '$lib/fetch/position/probes/propagate';

const RAD2DEG = 180 / Math.PI;
const SECONDS_PER_DAY = 86400;
const JD_J2000 = 2451545.0;
const KM_DAY_TO_AU_DAY = 1 / AU_KM;

function etToJd(et: number): number {
	return et / SECONDS_PER_DAY + JD_J2000;
}

function keplerPureElements(
	sub: KeplerPureElts,
	subStartEt: number,
	muKm3S2: number
): OrbitalElements | null {
	if (muKm3S2 <= 0) return null;
	const nRadS = Math.sqrt(muKm3S2 / (sub.aKm * sub.aKm * sub.aKm));
	const epoch = etToJd(subStartEt + sub.tAnchorOffsetS);
	return {
		a: sub.aKm / AU_KM,
		e: sub.e,
		i: sub.iRad * RAD2DEG,
		om: sub.om0 * RAD2DEG,
		w: sub.w0 * RAD2DEG,
		ma: sub.m0 * RAD2DEG,
		n: nRadS * RAD2DEG * SECONDS_PER_DAY,
		epoch,
		equatorial: false
	};
}

function keplerDriftElements(sub: KeplerDriftElts, subStartEt: number): OrbitalElements {
	const epoch = etToJd(subStartEt + sub.tAnchorOffsetS);
	return {
		a: sub.aKm / AU_KM,
		e: sub.e,
		i: sub.iRad * RAD2DEG,
		om: sub.om0 * RAD2DEG,
		w: sub.w0 * RAD2DEG,
		ma: sub.m0 * RAD2DEG,
		n: sub.nMeanRadS * RAD2DEG * SECONDS_PER_DAY,
		omDot: sub.omDot * RAD2DEG * SECONDS_PER_DAY,
		wDot: sub.wDot * RAD2DEG * SECONDS_PER_DAY,
		epoch,
		equatorial: false
	};
}

function chebyshevElements(
	probe: Probe,
	jd: number,
	muKm3S2: number,
	secondary: SecondaryPrimary | null
): OrbitalElements | null {
	if (muKm3S2 <= 0) return null;
	const fitMu = secondary?.fitCenterMuKm3S2 ?? muKm3S2;
	const state = probeStateKm(probe, jd, fitMu);
	if (!state) return null;
	const px = secondary ? state.position[0] - secondary.positionKm[0] : state.position[0];
	const py = secondary ? state.position[1] - secondary.positionKm[1] : state.position[1];
	const pz = secondary ? state.position[2] - secondary.positionKm[2] : state.position[2];
	const vx = secondary ? state.velocity[0] - secondary.velocityKmDay[0] : state.velocity[0];
	const vy = secondary ? state.velocity[1] - secondary.velocityKmDay[1] : state.velocity[1];
	const vz = secondary ? state.velocity[2] - secondary.velocityKmDay[2] : state.velocity[2];
	const muAuDay2 = muKm3S2 * KM3_S2_TO_AU3_DAY2;
	const r: [number, number, number] = [px / AU_KM, py / AU_KM, pz / AU_KM];
	const v: [number, number, number] = [
		vx * KM_DAY_TO_AU_DAY,
		vy * KM_DAY_TO_AU_DAY,
		vz * KM_DAY_TO_AU_DAY
	];
	return stateVectorToElements(r, v, muAuDay2, jd);
}

/** When the gravitational primary differs from the zone's stored fit center
 *  (lunar orbiters in `probes/earth-moon`, …), the chebyshev path subtracts
 *  the secondary's fit-center-relative state before deriving elements so the
 *  curve sits in the right reference frame. The Kepler-fit sub-chunks (which
 *  are already snapshots at the fit center) keep using `muKm3S2` directly —
 *  no transform exists for them without re-fitting, and they are only emitted
 *  in zones where the fit center IS the dominant primary. */
export interface SecondaryPrimary {
	/** Secondary primary's fit-center-relative position, ECLIPJ2000 km. */
	positionKm: [number, number, number];
	/** Secondary primary's fit-center-relative velocity, ECLIPJ2000 km/day. */
	velocityKmDay: [number, number, number];
	/** GM of the zone's stored fit center (km³/s²). The chebyshev finite-
	 *  difference state vector is muKm3S2-insensitive in practice (kepler_pure
	 *  is the only sub-chunk variant that depends on mu for evaluation), but
	 *  pass it explicitly so any future fit-center-dependent path stays correct. */
	fitCenterMuKm3S2: number;
}

export function probeOsculatingElements(
	probe: Probe,
	jd: number,
	muKm3S2: number,
	secondary: SecondaryPrimary | null = null
): OrbitalElements | null {
	const et = jdToEt(jd);
	const idx = findSubChunkIndex(probe, et);
	if (idx < 0) return null;
	const sub = probe.subChunks[idx];
	// A secondary primary forces the state-vector path for every sub-chunk
	// method: kepler_pure / kepler_drift store snapshots fit against the zone's
	// fit center, so reading their angles directly yields fit-center elements
	// regardless of where the probe actually sits gravitationally. The chebyshev
	// re-derive evaluates parent-relative position numerically and can subtract
	// the secondary's offset to land in the secondary frame.
	if (secondary && sub.method !== PROBE_METHOD_UNCOVERABLE) {
		return chebyshevElements(probe, jd, muKm3S2, secondary);
	}
	switch (sub.method) {
		case PROBE_METHOD_UNCOVERABLE:
			return null;
		case PROBE_METHOD_KEPLER_PURE:
			return keplerPureElements(sub, probe.subStartEt[idx], muKm3S2);
		case PROBE_METHOD_KEPLER_DRIFT:
			return keplerDriftElements(sub, probe.subStartEt[idx]);
		case PROBE_METHOD_CHEBYSHEV:
			return chebyshevElements(probe, jd, muKm3S2, null);
	}
}
