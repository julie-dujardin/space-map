/**
 * Osculating Keplerian elements from a probe's currently-active sub-chunk.
 *
 * Each sub-chunk is fit against the probe's stamped primary (Moon for lunar
 * orbiters, Sun for cruise, …), so elements come out in that primary's frame
 * directly — the caller passes the primary's GM and the elements are usable
 * by the trail refresh path without further transform.
 *
 *   - kepler_pure  → static OrbitalElements (no drift).
 *   - kepler_drift → OrbitalElements + omDot/wDot in deg/day.
 *   - chebyshev    → osculating elements from a state-vector sample.
 *   - uncoverable  → null; trail is skipped.
 *
 * Returns null when `mu <= 0` for the Kepler paths or when the chebyshev
 * state sample is null / degenerate.
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

function chebyshevElements(probe: Probe, jd: number, muKm3S2: number): OrbitalElements | null {
	if (muKm3S2 <= 0) return null;
	const state = probeStateKm(probe, jd, muKm3S2);
	if (!state) return null;
	const muAuDay2 = muKm3S2 * KM3_S2_TO_AU3_DAY2;
	const r: [number, number, number] = [
		state.position[0] / AU_KM,
		state.position[1] / AU_KM,
		state.position[2] / AU_KM
	];
	const v: [number, number, number] = [
		state.velocity[0] * KM_DAY_TO_AU_DAY,
		state.velocity[1] * KM_DAY_TO_AU_DAY,
		state.velocity[2] * KM_DAY_TO_AU_DAY
	];
	return stateVectorToElements(r, v, muAuDay2, jd);
}

export function probeOsculatingElements(
	probe: Probe,
	jd: number,
	muKm3S2: number
): OrbitalElements | null {
	const et = jdToEt(jd);
	const idx = findSubChunkIndex(probe, et);
	if (idx < 0) return null;
	const sub = probe.subChunks[idx];
	switch (sub.method) {
		case PROBE_METHOD_UNCOVERABLE:
			return null;
		case PROBE_METHOD_KEPLER_PURE:
			return keplerPureElements(sub, probe.subStartEt[idx], muKm3S2);
		case PROBE_METHOD_KEPLER_DRIFT:
			return keplerDriftElements(sub, probe.subStartEt[idx]);
		case PROBE_METHOD_CHEBYSHEV:
			return chebyshevElements(probe, jd, muKm3S2);
	}
}
