/**
 * Back-populate a probe trail buffer by walking jd backwards from `centerJd`,
 * placing samples via chord-error adaptive subdivision (dense near
 * periapsis/gravity assists, sparse near apoapsis). `buf.epsilonScene ===
 * Infinity` degenerates to uniform `stepDays` sampling. Samples live in the
 * fit-center-relative scene frame; the renderer adds the parent position at
 * draw time.
 *
 * Stops walking once the probe's stamped primary no longer matches
 * `currentParentKey` — mixing frames inside one buffer warps the trail.
 */

import {
	ADAPTIVE_MAX_STEP_FACTOR,
	ADAPTIVE_MIN_STEP_FACTOR
} from '$lib/fetch/position/trail-buffer';
import { AU_SCALE } from '$lib/math/units';
import { orbitalElementsToPositionJD } from '$lib/math/orbit/position';
import { resolveProbePrimary } from '$lib/fetch/position/probes/primary';
import { probeStateElements } from '$lib/fetch/position/probes/elements';
import { probePositionScene } from '$lib/fetch/position/probes/propagate';
import type { ChebyshevStore } from '$lib/fetch/position/chebyshev/store';
import type { ProbeStore } from '$lib/fetch/position/probes/store';
import type { TrailBuffer } from '$lib/fetch/position/trail-buffer';
import type { OrbitalElements } from '$lib/types/objects';

type Vec3 = [number, number, number];

/** One halo period is ~180 d; a little more closes the loop with margin. */
const LAGRANGE_TRAIL_SPAN_DAYS = 200;
/** Escape trail length as a share of the distance from the Sun: a fixed time
 *  span is a speck in interstellar space and too long in the inner system. */
export const ESCAPE_TRAIL_SUN_SHARE = 0.35;
type Sample = { jd: number; pos: Vec3 };
type Sampler = (t: number) => Vec3 | null;
/** Sampler that carries the walk on past `oldestJd`, where data ran out. */
type TailSampler = (oldestJd: number) => Sampler | null;

/**
 * Trail sampling parameters from osculating elements in the trail's frame.
 * `stepDays` spreads the sample budget over one orbital period (or
 * `fallbackSpanDays` if hyperbolic/unavailable). Epsilon scales to periapsis
 * q = a(1−e), not a, so facets stay small where the curve is sharpest and
 * gravity assists sample adaptively too; Infinity (uniform) until elements
 * resolve. `spanDays` caps the back-fill at one period for ellipses, but is
 * uncapped for hyperbolic flybys, where there's no loop to retrace.
 *
 * A Lagrange loop (`lagrange`) is not an orbit about the fit centre: the
 * elements would size the walk to a meaningless geocentric period, so it
 * gets one halo period, sampled uniformly.
 *
 * A `heliocentric` open orbit is an escape trail: its length follows the
 * distance from the Sun (`lengthShare`) instead of a time span.
 *
 * Frame-dependent throughout — a reseed against a new parent MUST re-derive
 * these via `TrailBuffer.reconfigure`, or the walk samples the wrong scale.
 */
export function deriveProbeTrailParams(
	elements: OrbitalElements | null,
	fallbackSpanDays: number,
	capacity: number,
	lagrange = false,
	heliocentric = false
): { stepDays: number; epsilonScene: number; spanDays: number; lengthShare: number } {
	if (lagrange) {
		return {
			stepDays: LAGRANGE_TRAIL_SPAN_DAYS / capacity,
			epsilonScene: Infinity,
			spanDays: LAGRANGE_TRAIL_SPAN_DAYS,
			lengthShare: 0
		};
	}
	const periapsisAu = elements ? elements.a * (1 - elements.e) : 0;
	const epsilonScene = periapsisAu > 0 ? periapsisAu * AU_SCALE * 0.0001 : Infinity;
	if (heliocentric && elements !== null && elements.e >= 1 && isFinite(epsilonScene)) {
		return {
			stepDays: fallbackSpanDays > 0 ? fallbackSpanDays / capacity : 1,
			epsilonScene,
			spanDays: Infinity,
			lengthShare: ESCAPE_TRAIL_SUN_SHARE
		};
	}
	const elliptical = elements !== null && elements.n > 0;
	const periodDays = elliptical ? 360 / elements.n : fallbackSpanDays;
	const stepDays = periodDays > 0 ? periodDays / capacity : 1;
	const spanDays = !elliptical && isFinite(epsilonScene) ? Infinity : stepDays * capacity;
	return { stepDays, epsilonScene, spanDays, lengthShare: 0 };
}

/** Prefer the zone whose fit center IS the trail's own frame, so overlapping
 *  zones resolve in `currentParentKey`'s frame — a heliocentric trail keeps
 *  its interplanetary fit across a flyby instead of dropping to the planet
 *  zone and bridging the encounter with a straight line. */
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
		// The gate below discards any other frame, so a stamped small body is
		// live by construction when it IS the trail's own parent.
		const past = resolveProbePrimary(
			located.probe,
			t,
			located.fitCenterNaifId,
			cheb,
			(id) => id === currentParentKey
		);
		if (!past || past.id !== currentParentKey) return null;
		return probePositionScene(located.probe, t, past.muKm3S2);
	};
}

/**
 * Kepler orbit about the trail's parent from the osculating state at the
 * oldest sample, for an escape trail whose data stops at a chunk that is not
 * loaded. Null where the data truly ends (launch, a frame change): there the
 * extrapolation would draw a path the probe never flew.
 */
export function buildKeplerTailSampler(
	probeStore: ProbeStore,
	cheb: ChebyshevStore | null,
	probeId: string,
	currentParentKey: string
): TailSampler {
	const isPreferred = frameFitPreference(currentParentKey);
	return (oldestJd) => {
		if (!probeStore.unloadedBefore(probeId, oldestJd, isPreferred)) return null;
		const located = probeStore.probeWithCenter(probeId, oldestJd, isPreferred);
		if (!located) return null;
		const past = resolveProbePrimary(
			located.probe,
			oldestJd,
			located.fitCenterNaifId,
			cheb,
			(id) => id === currentParentKey
		);
		if (!past || past.id !== currentParentKey) return null;
		const elements = probeStateElements(located.probe, oldestJd, past.muKm3S2);
		if (!elements) return null;
		return (t) => orbitalElementsToPositionJD(elements, t);
	};
}

/** Chord-error metric: distance from the curve's midpoint to the chord's
 *  midpoint. Smooth regions tolerate long segments; sharp turns need
 *  subdivision. Null when the midpoint sample is unavailable. */
function chordError(sample: Sampler, t0: number, p0: Vec3, t1: number, p1: Vec3): number | null {
	const mid = sample((t0 + t1) / 2);
	if (!mid) return null;
	const dx = mid[0] - (p0[0] + p1[0]) / 2;
	const dy = mid[1] - (p0[1] + p1[1]) / 2;
	const dz = mid[2] - (p0[2] + p1[2]) / 2;
	return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/** Scale-relative slack on the chord tolerance: a segment is acceptable when
 *  its error ≤ `max(epsilon, TRAIL_REL_TOL · chordLength)`. Far from the fit
 *  center, where Float32 Chebyshev noise dwarfs the periapsis-scaled
 *  `epsilon`, this bridges sub-chunk-boundary noise with a long segment
 *  instead of crawling at `minStep`. Near periapsis `epsilon` still dominates. */
const TRAIL_REL_TOL = 0.005;

function withinTolerance(err: number | null, from: Vec3, end: Vec3, epsilon: number): boolean {
	if (err === null) return false;
	const chord = Math.hypot(end[0] - from[0], end[1] - from[1], end[2] - from[2]);
	return err <= Math.max(epsilon, TRAIL_REL_TOL * chord);
}

/** Distance from `p` to the segment `a`–`b`. */
function segmentDistance(p: Vec3, a: Vec3, b: Vec3): number {
	const abx = b[0] - a[0];
	const aby = b[1] - a[1];
	const abz = b[2] - a[2];
	const len2 = abx * abx + aby * aby + abz * abz;
	const u =
		len2 > 0
			? Math.max(
					0,
					Math.min(1, ((p[0] - a[0]) * abx + (p[1] - a[1]) * aby + (p[2] - a[2]) * abz) / len2)
				)
			: 0;
	return Math.hypot(p[0] - a[0] - u * abx, p[1] - a[1] - u * aby, p[2] - a[2] - u * abz);
}

/** Largest step in `[minStep, maxStep]` from `tFrom` (dir −1/+1) whose chord
 *  stays within tolerance. Binary search, with a fast path that accepts
 *  `maxStep` outright in low-curvature regions. Null when no candidate in the
 *  window has a valid sample. */
function findAdaptiveStep(
	sample: Sampler,
	tFrom: number,
	pFrom: Vec3,
	epsilon: number,
	minStep: number,
	maxStep: number,
	dir: number
): Sample | null {
	const within = (err: number | null, end: Vec3): boolean =>
		withinTolerance(err, pFrom, end, epsilon);
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
	const tail =
		buf.lengthShare > 0
			? buildKeplerTailSampler(probeStore, cheb, probeId, currentParentKey)
			: undefined;
	backfillTrailFromSampler(buf, sample, centerJd, tail);
}

/** Straight stretches at the longest step take a quarter of the samples, so a
 *  flyby inside the escape trail still has room to subdivide. */
const ESCAPE_STRAIGHT_SAMPLE_SHARE = 1 / 4;

/** Widen an escape trail's step to its length target: the default one-chunk
 *  step would spend the whole budget on a few years of straight line. */
function fitEscapeStep(
	buf: TrailBuffer,
	sample: Sampler,
	headJd: number,
	headPos: Vec3,
	length: number
): void {
	const prev = sample(headJd - 1);
	if (!prev) return;
	const speed = Math.hypot(headPos[0] - prev[0], headPos[1] - prev[1], headPos[2] - prev[2]);
	if (!(speed > 0)) return;
	const days = length / speed;
	const samples = buf.capacity * ESCAPE_STRAIGHT_SAMPLE_SHARE;
	buf.stepDays = Math.max(buf.stepDays, days / (samples * ADAPTIVE_MAX_STEP_FACTOR));
}

/** Back-fill `buf` by walking `sample` backwards from `centerJd`, same
 *  chord-error subdivision as {@link extendProbeTrailBuffer}. Split out from
 *  {@link populateProbeTrailBuffer} so tests can drive the walk without a store.
 *  An escape trail (`buf.lengthShare`) stops at its length target, and `tail`
 *  carries it on where the data runs out first. */
export function backfillTrailFromSampler(
	buf: TrailBuffer,
	sample: Sampler,
	centerJd: number,
	tail?: TailSampler
): void {
	const headPos = sample(centerJd);
	if (!headPos) return;
	const lengthLimit =
		buf.lengthShare > 0
			? buf.lengthShare * Math.hypot(headPos[0], headPos[1], headPos[2])
			: Infinity;
	if (isFinite(lengthLimit)) fitEscapeStep(buf, sample, centerJd, headPos, lengthLimit);

	// Adaptive path: walk back via chord-error. `epsilonScene = Infinity`
	// degenerates to uniform `stepDays` because chord error never exceeds
	// Infinity, so `findAdaptiveStep` always accepts `maxStep`. The walk is
	// also capped at `buf.spanDays` — one orbital period for elliptical
	// orbits, so the 512-sample budget concentrates on the most recent period
	// instead of being spread across multiple retraced loops; unbounded for
	// hyperbolic flyby frames, where coverage and the parent gate bound it.
	const samples: Sample[] = [{ jd: centerJd, pos: headPos }];
	if (isFinite(buf.epsilonScene)) {
		const maxStep = buf.stepDays * ADAPTIVE_MAX_STEP_FACTOR;
		const minStep = buf.stepDays * ADAPTIVE_MIN_STEP_FACTOR;
		const spanLimitJd = centerJd - buf.spanDays;
		let walk = sample;
		let tailTried = tail === undefined;
		let length = 0;
		while (samples.length < buf.capacity && length < lengthLimit) {
			const head = samples[samples.length - 1];
			if (head.jd <= spanLimitJd) break;
			const step = () =>
				findAdaptiveStep(walk, head.jd, head.pos, buf.epsilonScene, minStep, maxStep, -1);
			let prev = step();
			if (!prev && !tailTried && tail) {
				tailTried = true;
				const extension = tail(head.jd);
				if (extension) {
					walk = extension;
					prev = step();
				}
			}
			if (!prev) break;
			if (prev.jd < spanLimitJd) {
				// Clamp the final segment to the span boundary so the trail
				// ends cleanly at one period back rather than overshooting.
				const clampPos = walk(spanLimitJd);
				if (clampPos) samples.push({ jd: spanLimitJd, pos: clampPos });
				break;
			}
			length += Math.hypot(
				prev.pos[0] - head.pos[0],
				prev.pos[1] - head.pos[1],
				prev.pos[2] - head.pos[2]
			);
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

/** Extend a buffer forward from its newest sample to `headJd`, inserting
 *  intermediate samples with the same chord-error subdivision as the
 *  back-fill — the live-play appender only adds the current frame's
 *  position, so a fast periapsis pass at high time-speed would otherwise
 *  draw one long facet. Capped at capacity iterations.
 *
 *  A step that leaves the newest sample redundant moves it instead of adding
 *  one: one sample per frame would fill the ring in seconds of fast playback
 *  and cut the trail to hours. */
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
	const before: Vec3 = [0, 0, 0];
	let t0 = lastJd;
	let p0 = lastPos;
	for (let i = 0; i < buf.capacity; i++) {
		if (headJd - t0 <= minStep) break;
		const stepCap = Math.min(maxStep, headJd - t0);
		const next = findAdaptiveStep(sample, t0, p0, buf.epsilonScene, minStep, stepCap, 1);
		if (!next || next.jd <= t0) break;
		const beforeJd = buf.readSecondNewest(before);
		if (
			next.jd - beforeJd <= maxStep &&
			withinTolerance(segmentDistance(p0, before, next.pos), before, next.pos, buf.epsilonScene) &&
			withinTolerance(
				chordError(sample, beforeJd, before, next.jd, next.pos),
				before,
				next.pos,
				buf.epsilonScene
			)
		) {
			buf.replaceNewest(next.jd, next.pos[0], next.pos[1], next.pos[2]);
		} else {
			buf.append(next.jd, next.pos[0], next.pos[1], next.pos[2]);
		}
		t0 = next.jd;
		p0 = next.pos;
	}
}
