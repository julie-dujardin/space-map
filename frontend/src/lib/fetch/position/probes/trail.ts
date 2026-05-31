/**
 * Back-populate a probe trail buffer by walking jd backwards from `centerJd`,
 * placing samples via chord-error adaptive subdivision (dense near
 * periapsis/gravity assists, sparse near apoapsis). When `buf.epsilonScene` is
 * `Infinity` the loop degenerates to uniform `stepDays` sampling — the legacy
 * behaviour. Samples live in the probe's fit-center-relative scene frame; the
 * renderer adds the current parent position at draw time.
 *
 * Stops walking back once the probe's stamped primary at the candidate jd no
 * longer matches `currentParentKey` — cross-zone transitions move the probe
 * under a new fit center, and mixing frames inside one buffer warps the trail.
 * Called from `processProbes` on chunk load (cold-start back-fill) and from
 * `updatePositions` when the live parent flips mid-play (cruise → captured
 * orbit).
 */

import {
	ADAPTIVE_MAX_STEP_FACTOR,
	ADAPTIVE_MIN_STEP_FACTOR
} from '$lib/fetch/position/trail-buffer';
import { resolvePrimaryOverride } from '$lib/fetch/position/probes/primary';
import { probePositionScene } from '$lib/fetch/position/probes/propagate';
import { getGmKm3s2 } from '$lib/fetch/systems-global';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';

type Vec3 = [number, number, number];
type Sample = { jd: number; pos: Vec3 };
type Sampler = (t: number) => Vec3 | null;

/**
 * Parent-relative probe position at `t`, gated on the located probe's primary
 * matching `currentParentKey`. Returns null on coverage gap or zone mismatch.
 */
function buildParentGatedSampler(
	probeStore: ProbeStore,
	cheb: ChebyshevStore | null,
	probeId: string,
	currentParentKey: string,
	isPreferred?: (fitCenterNaif: number) => boolean
): Sampler {
	return (t) => {
		const located = probeStore.probeWithCenter(probeId, t, isPreferred);
		if (!located) return null;
		const pastZoneKey = `naif-${located.fitCenterNaifId}`;
		const pastOverride = resolvePrimaryOverride(located.probe, t, pastZoneKey, cheb);
		const pastPrimaryKey = pastOverride ? pastOverride.id : pastZoneKey;
		if (pastPrimaryKey !== currentParentKey) return null;
		const pastPrimaryNaif = pastOverride ? pastOverride.naifId : located.fitCenterNaifId;
		const pastMu = getGmKm3s2(pastPrimaryNaif) ?? 0;
		return probePositionScene(located.probe, t, pastMu);
	};
}

/**
 * Chord-error metric: distance from the curve's midpoint to the chord's
 * midpoint. Smooth low-curvature regions have small chord error and tolerate
 * long segments; sharp turns have large chord error and need subdivision.
 * Returns null when the midpoint sample is unavailable (caller treats as
 * "subdivide further" — we don't have enough information to commit to a long
 * segment).
 */
function chordError(sample: Sampler, t0: number, p0: Vec3, t1: number, p1: Vec3): number | null {
	const mid = sample((t0 + t1) / 2);
	if (!mid) return null;
	const dx = mid[0] - (p0[0] + p1[0]) / 2;
	const dy = mid[1] - (p0[1] + p1[1]) / 2;
	const dz = mid[2] - (p0[2] + p1[2]) / 2;
	return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/**
 * Largest dt in `[minStep, maxStep]` such that the chord from `t1 - dt` to
 * `t1` deviates from the curve by ≤ `epsilon`. Binary search over dt, with a
 * fast path that accepts `maxStep` outright in low-curvature regions. Returns
 * null when no candidate within the window has a valid sample (coverage gap or
 * zone mismatch over the whole window).
 */
function findPreviousTarget(
	sample: Sampler,
	t1: number,
	p1: Vec3,
	epsilon: number,
	minStep: number,
	maxStep: number
): Sample | null {
	const tFar = t1 - maxStep;
	const pFar = sample(tFar);
	if (pFar !== null) {
		const err = chordError(sample, tFar, pFar, t1, p1);
		if (err !== null && err <= epsilon) return { jd: tFar, pos: pFar };
	}
	let lo = minStep;
	let hi = maxStep;
	let best: Sample | null = null;
	const resolution = minStep * 0.25;
	for (let i = 0; i < 16; i++) {
		const dt = (lo + hi) / 2;
		const t = t1 - dt;
		const p = sample(t);
		if (p === null) {
			hi = dt;
			continue;
		}
		const err = chordError(sample, t, p, t1, p1);
		if (err === null || err > epsilon) {
			hi = dt;
		} else {
			lo = dt;
			best = { jd: t, pos: p };
		}
		if (hi - lo < resolution) break;
	}
	if (best) return best;
	// Couldn't satisfy tolerance even at minStep — accept minStep as fallback so
	// the trail keeps extending across the highest-curvature regions.
	const t = t1 - minStep;
	const p = sample(t);
	return p ? { jd: t, pos: p } : null;
}

export function populateProbeTrailBuffer(
	buf: TrailBuffer,
	probeStore: ProbeStore,
	cheb: ChebyshevStore | null,
	probeId: string,
	currentParentKey: string,
	centerJd: number,
	isPreferred?: (fitCenterNaif: number) => boolean
): void {
	const sample = buildParentGatedSampler(probeStore, cheb, probeId, currentParentKey, isPreferred);
	const headPos = sample(centerJd);
	if (!headPos) return;

	// Adaptive path: walk back via chord-error. `epsilonScene = Infinity`
	// degenerates to uniform `stepDays` because chord error never exceeds
	// Infinity, so `findPreviousTarget` always accepts `maxStep`. The walk is
	// also capped at one canonical orbital span (`stepDays * capacity`) so the
	// 512-sample budget concentrates on the most recent period instead of
	// being spread across multiple retraced loops.
	const samples: Sample[] = [{ jd: centerJd, pos: headPos }];
	if (isFinite(buf.epsilonScene)) {
		const maxStep = buf.stepDays * ADAPTIVE_MAX_STEP_FACTOR;
		const minStep = buf.stepDays * ADAPTIVE_MIN_STEP_FACTOR;
		const spanLimitJd = centerJd - buf.stepDays * buf.capacity;
		while (samples.length < buf.capacity) {
			const head = samples[samples.length - 1];
			if (head.jd <= spanLimitJd) break;
			const prev = findPreviousTarget(
				sample,
				head.jd,
				head.pos,
				buf.epsilonScene,
				minStep,
				maxStep
			);
			if (!prev) break;
			if (prev.jd < spanLimitJd) {
				// Clamp the final segment to the span boundary so the trail
				// ends cleanly at one period back rather than overshooting.
				const clampPos = sample(spanLimitJd);
				if (clampPos) samples.push({ jd: spanLimitJd, pos: clampPos });
				break;
			}
			samples.push(prev);
		}
	} else {
		// Legacy uniform fallback: walk backwards at fixed `stepDays`. Mirrors
		// the original loop including the skip-on-zone-mismatch behaviour
		// (`continue` rather than break) so we don't change semantics when
		// adaptive sampling is disabled.
		for (let k = 1; k < buf.capacity; k++) {
			const t = centerJd - k * buf.stepDays;
			const p = sample(t);
			if (!p) continue;
			samples.push({ jd: t, pos: p });
		}
	}

	for (let i = samples.length - 1; i >= 0; i--) {
		const s = samples[i];
		buf.append(s.jd, s.pos[0], s.pos[1], s.pos[2]);
	}
}
