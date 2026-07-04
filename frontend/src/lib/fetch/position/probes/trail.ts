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
 * Prefer the zone whose fit center IS the trail's own frame, so overlapping
 * zones resolve in `currentParentKey`'s frame. A heliocentric trail keeps the
 * interplanetary fit across a flyby instead of falling to the planet zone (whose
 * samples the gate then drops, bridging the encounter with a straight line).
 * Override frames (probe captured around a moon) match no zone fit center and
 * fall through to the resolver's default order — unchanged.
 */
export function frameFitPreference(currentParentKey: string): (fitCenterNaif: number) => boolean {
	const frameNaif = Number(currentParentKey.slice('naif-'.length));
	return (fitCenterNaif) => fitCenterNaif === frameNaif;
}

/**
 * Parent-relative probe position at `t`, gated on the located probe's primary
 * matching `currentParentKey`. Returns null on coverage gap or zone mismatch.
 */
export function buildParentGatedSampler(
	probeStore: ProbeStore,
	cheb: ChebyshevStore | null,
	probeId: string,
	currentParentKey: string
): Sampler {
	const isPreferred = frameFitPreference(currentParentKey);
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
 * Scale-relative slack added to the absolute chord tolerance: a segment is
 * acceptable when its chord error ≤ `max(epsilon, TRAIL_REL_TOL · chordLength)`.
 * The relative term bounds the facet *angle* (~4·TRAIL_REL_TOL rad) so far from
 * the fit center — where a Float32 Chebyshev fit's noise floor dwarfs the
 * periapsis-scaled `epsilon` — the walk bridges sub-chunk-boundary noise with a
 * long segment instead of crawling at `minStep` and emitting near-duplicate,
 * noise-angled points. Near periapsis `epsilon` dominates and keeps it sharp.
 */
const TRAIL_REL_TOL = 0.005;

/**
 * Largest step in `[minStep, maxStep]` from `tFrom` in time direction `dir`
 * (−1 walking back, +1 walking forward) whose chord to `tFrom` stays within
 * tolerance of the curve. Binary search, with a fast path that accepts
 * `maxStep` outright in low-curvature regions. Returns null when no candidate
 * in the window has a valid sample (coverage gap or zone mismatch throughout).
 */
function findAdaptiveStep(
	sample: Sampler,
	tFrom: number,
	pFrom: Vec3,
	epsilon: number,
	minStep: number,
	maxStep: number,
	dir: number
): Sample | null {
	const within = (err: number | null, end: Vec3): boolean => {
		if (err === null) return false;
		const chord = Math.hypot(end[0] - pFrom[0], end[1] - pFrom[1], end[2] - pFrom[2]);
		return err <= Math.max(epsilon, TRAIL_REL_TOL * chord);
	};
	const tFar = tFrom + dir * maxStep;
	const pFar = sample(tFar);
	if (pFar !== null) {
		const err = chordError(sample, tFrom, pFrom, tFar, pFar);
		if (within(err, pFar)) return { jd: tFar, pos: pFar };
	}
	let lo = minStep;
	let hi = maxStep;
	let best: Sample | null = null;
	const resolution = minStep * 0.25;
	for (let i = 0; i < 16; i++) {
		const dt = (lo + hi) / 2;
		const t = tFrom + dir * dt;
		const p = sample(t);
		if (p === null) {
			hi = dt;
			continue;
		}
		const err = chordError(sample, tFrom, pFrom, t, p);
		if (!within(err, p)) {
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
	const t = tFrom + dir * minStep;
	const p = sample(t);
	return p ? { jd: t, pos: p } : null;
}

export function populateProbeTrailBuffer(
	buf: TrailBuffer,
	probeStore: ProbeStore,
	cheb: ChebyshevStore | null,
	probeId: string,
	currentParentKey: string,
	centerJd: number
): void {
	const sample = buildParentGatedSampler(probeStore, cheb, probeId, currentParentKey);
	const headPos = sample(centerJd);
	if (!headPos) return;

	// Adaptive path: walk back via chord-error. `epsilonScene = Infinity`
	// degenerates to uniform `stepDays` because chord error never exceeds
	// Infinity, so `findAdaptiveStep` always accepts `maxStep`. The walk is
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
			const prev = findAdaptiveStep(
				sample,
				head.jd,
				head.pos,
				buf.epsilonScene,
				minStep,
				maxStep,
				-1
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

/**
 * Extend a buffer forward from its newest sample (`lastJd`/`lastPos`) to
 * `headJd`, inserting intermediate samples with the same chord-error
 * subdivision as the back-fill. The live-play appender only ever adds the
 * current frame's position, so a fast periapsis pass at high time-speed jumps a
 * large arc per frame and draws one long facet; this fills those gaps. `sample`
 * must return positions in the buffer's frame. Iteration is capped at capacity
 * so a near-span gap can't spin (the ring overwrites older samples anyway).
 */
export function extendProbeTrailBuffer(
	buf: TrailBuffer,
	sample: Sampler,
	lastJd: number,
	lastPos: Vec3,
	headJd: number
): void {
	if (!isFinite(buf.epsilonScene)) return;
	const maxStep = buf.stepDays * ADAPTIVE_MAX_STEP_FACTOR;
	const minStep = buf.stepDays * ADAPTIVE_MIN_STEP_FACTOR;
	let t0 = lastJd;
	let p0 = lastPos;
	for (let i = 0; i < buf.capacity; i++) {
		if (headJd - t0 <= minStep) break;
		const stepCap = Math.min(maxStep, headJd - t0);
		const next = findAdaptiveStep(sample, t0, p0, buf.epsilonScene, minStep, stepCap, 1);
		if (!next || next.jd <= t0) break;
		buf.append(next.jd, next.pos[0], next.pos[1], next.pos[2]);
		t0 = next.jd;
		p0 = next.pos;
	}
}
