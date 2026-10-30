"""Split a spinner's mission into spans, each with one fixed-rate baseline.

A fixed spin baseline cancels the spin only while rate and axis hold. Where
the residual against it turns past the alias angle in one seed step, the
adaptive sampler aliases it and whole days come out wrong. Juno steps between
1 and 2 RPM across mission phases, and HUYGENS spins down slowly through its
coast. So the planner cuts at phase changes, then cuts each phase again where
the residual against the span's baseline turns too fast. Where no baseline
holds for a useful time (the HUYGENS descent), the span is raw and gets a seed
step short enough for its top spin rate.

A non-spinner returns a single raw span: raw motion already samples fine, and
an inverse spin would only add curvature. The spinner test is the same alias
gate the extractor uses.
"""

import itertools
import logging
import math
from dataclasses import dataclass

import numpy as np
import spiceypy

from .adaptive import SEED_DT_S
from .baseline import SpinBaseline, fit_spin_baseline
from .quaternion import q_conj, q_mul, q_mul_rows
from .sample import sample_truth

logger = logging.getLogger(__name__)

# Spin-rate timeline resolution — omega probes spread across the mission. The
# transitions we care about (1↔2 RPM) last months, so a coarse grid finds them.
SEG_MAX_PROBES = 1500
# Close-pair spacing for a local angular-velocity probe (s). Small enough that a
# fast spin turns < 10° between the pair, so the chord tracks the rate.
OMEGA_DDT = 0.5
# New phase when the local omega vector departs this fraction from the phase's
# running reference: a rate step or an axis reorientation. The 1↔2 RPM steps
# are a 100% change, far above the threshold; in-span jitter is a few percent,
# far below.
SEG_REL_TOL = 0.2
# Don't spawn a phase shorter than this: a brief maneuver keeps its
# neighbour's phase, and the residual check cuts it out if it must.
SEG_MIN_S = 6 * 3600.0
# Boundary bisection depth: localises a cut to (probe gap)/2³⁰ ≈ exact, so a
# span never inherits a sliver of the next one's wrong-rate spin.
REFINE_ITERS = 30
# Short dense fit window: a constant rate fits from sub-degree-spaced samples
# over a few hundred seconds. A long sparse window aliases the fit itself.
FIT_SHORT_S = 600.0
FIT_SHORT_HZ = 20.0
# A baseline that holds for less than this is not worth a span and a chunk
# file of its own, so the stretch is sampled raw.
SPAN_MIN_S = 3600.0
# The residual check samples each seed step so that one sub-step turns at most
# this far, even against a wrong baseline. A turn of many rounds then cannot
# alias to a small one.
SUB_TURN_RAD = math.pi / 2
# Spacing of the rate scan that sets the seed step of a raw span.
RATE_SCAN_S = 10.0
# The search for the end of a raw stretch stops at this precision (s). Each
# step fits a baseline, so it does not bisect to the bottom.
RAW_EDGE_TOL_S = 1.0


@dataclass(frozen=True)
class SpinSegment:
    """One mission span, the baseline to subtract over it (None = raw) and the
    seed step of its adaptive sampling."""

    start_et: float
    end_et: float
    baseline: SpinBaseline | None
    seed_dt: float = SEED_DT_S


def is_spin_plan(segments: list[SpinSegment]) -> bool:
    """True for a spinner's plan: anything but raw spans on the default seed."""
    return any(s.baseline is not None or s.seed_dt != SEED_DT_S for s in segments)


def plan_segments(
    frame: str, t0: float, t1: float, *, alias_angle: float, seed_dt: float
) -> list[SpinSegment]:
    """Partition `[t0, t1]` into spans, fitting a baseline per span. Returns
    a single raw span for a non-spinner."""
    ets = spin_timeline_ets(t0, t1)
    omegas = spin_omegas(frame, ets)
    return segments_from_timeline(
        frame, t0, t1, ets, omegas, alias_angle=alias_angle, seed_dt=seed_dt
    )


def spin_timeline_ets(t0: float, t1: float) -> np.ndarray:
    """`t0`, then the multiples of a power-of-two step inside `[t0, t1]`.

    The grid starts at ET 0, and the step changes only when the span doubles.
    So a CK that extends the span keeps every earlier probe, and the cuts found
    from them do not move.
    """
    step = 2.0 ** math.ceil(math.log2(max(1.0, (t1 - t0) / SEG_MAX_PROBES)))
    first = math.floor(t0 / step) + 1
    last = math.floor((t1 - OMEGA_DDT) / step)
    return np.concatenate([[t0], np.arange(first, last + 1) * step])


def spin_omegas(frame: str, ets: np.ndarray) -> list[np.ndarray | None]:
    """Local angular-velocity vector at each epoch (None in a CK gap)."""
    return [_omega(frame, float(e)) for e in ets]


def is_spinner(
    omegas: list[np.ndarray | None], *, alias_angle: float, seed_dt: float
) -> bool:
    """True when the median spin turns the craft past `alias_angle` between
    seed samples."""
    speeds = [float(np.linalg.norm(o)) for o in omegas if o is not None]
    return bool(speeds) and float(np.median(speeds)) * seed_dt > alias_angle


def segments_from_timeline(
    frame: str,
    t0: float,
    t1: float,
    ets: np.ndarray,
    omegas: list[np.ndarray | None],
    *,
    alias_angle: float,
    seed_dt: float,
) -> list[SpinSegment]:
    """`plan_segments` after the timeline: cut at phase changes, then split
    each phase where its baseline stops holding."""
    if not is_spinner(omegas, alias_angle=alias_angle, seed_dt=seed_dt):
        return [SpinSegment(t0, t1, None, seed_dt)]

    phases = [t0, *_phase_boundaries(frame, ets, omegas), t1]
    check = _Check(frame, ets, alias_angle, seed_dt)
    segments = [seg for a, b in itertools.pairwise(phases) for seg in check.split(a, b)]
    if len(segments) > 1:
        logger.info(
            "attitude: %s — %d spin spans at %s RPM",
            frame,
            len(segments),
            ", ".join(
                f"{s.baseline.rate_rad_s / (2 * math.pi) * 60:.1f}"
                if s.baseline
                else "raw"
                for s in segments
            ),
        )
    return segments


def _omega(frame: str, et: float, ddt: float = OMEGA_DDT) -> np.ndarray | None:
    """Body-frame angular velocity (rad/s) from a close `pxform` pair; None on a
    gap. Direction is the spin axis, magnitude the rate — stable per phase."""
    try:
        qa = spiceypy.m2q(spiceypy.pxform("J2000", frame, et))
        qb = spiceypy.m2q(spiceypy.pxform("J2000", frame, et + ddt))
    except spiceypy.exceptions.SpiceyError:
        return None
    rel = q_mul(qb, q_conj(qa))
    angle = 2.0 * math.acos(min(1.0, abs(float(rel[0]))))
    axis = rel[1:]
    norm = float(np.linalg.norm(axis))
    if norm < 1e-12 or angle < 1e-12:
        return np.zeros(3)
    sign = 1.0 if rel[0] >= 0 else -1.0
    return (axis / norm) * (angle / ddt) * sign


def _phase_boundaries(
    frame: str, ets: np.ndarray, omegas: list[np.ndarray | None]
) -> list[float]:
    """Refined transition epochs where the local spin leaves the current phase.

    Gaps don't break a phase: a post-gap probe still matching the running
    reference continues the same span (the transition, if any, happened in the
    gap and is placed at the post-gap coverage edge by the bisection).
    """
    raw: list[float] = []
    ref: np.ndarray | None = None
    acc: list[np.ndarray] = []
    last_valid = 0
    for i, o in enumerate(omegas):
        if o is None:
            continue
        if ref is None:
            ref, acc, last_valid = o, [o], i
            continue
        rel = float(np.linalg.norm(o - ref)) / max(1e-9, float(np.linalg.norm(ref)))
        if rel > SEG_REL_TOL:
            raw.append(
                _refine_boundary(frame, float(ets[last_valid]), float(ets[i]), ref, o)
            )
            ref, acc = o, [o]
        else:
            acc.append(o)
            ref = np.median(acc, axis=0)
        last_valid = i
    return _enforce_min_span(raw, float(ets[0]), float(ets[-1]))


def _refine_boundary(
    frame: str, lo: float, hi: float, ref_lo: np.ndarray, ref_hi: np.ndarray
) -> float:
    """Bisect `[lo, hi]` for the epoch where the spin switches phase, returning
    the first time classified into the new phase. A gap at the midpoint biases
    toward `hi` (the new phase's coverage)."""
    for _ in range(REFINE_ITERS):
        mid = 0.5 * (lo + hi)
        o = _omega(frame, mid)
        if o is None or float(np.linalg.norm(o - ref_lo)) > float(
            np.linalg.norm(o - ref_hi)
        ):
            hi = mid
        else:
            lo = mid
    return hi


def _enforce_min_span(boundaries: list[float], t0: float, t1: float) -> list[float]:
    """Drop boundaries that would carve a span shorter than `SEG_MIN_S`."""
    kept: list[float] = []
    prev = t0
    for b in boundaries:
        if b - prev >= SEG_MIN_S and t1 - b >= SEG_MIN_S:
            kept.append(b)
            prev = b
    return kept


class _Check:
    """Splits a phase where the residual against a span's baseline turns past
    the alias angle in one seed step.

    The check runs at the timeline probes, then bisects between the last probe
    that holds and the first that fails. It does not run at a cut: the minute
    of a Juno spin change sits there and the sampler handles it. It does run
    at the coverage start, a probe, because HUYGENS starts before its
    separation spin-up, and at each candidate end of a raw stretch.
    """

    def __init__(
        self, frame: str, probes: np.ndarray, alias_angle: float, seed_dt: float
    ) -> None:
        self.frame = frame
        self.probes = probes
        self.alias_angle = alias_angle
        self.seed_dt = seed_dt

    def split(self, start: float, end: float) -> list[SpinSegment]:
        """The spans of the phase `[start, end]`."""
        out: list[SpinSegment] = []
        s = start
        while s < end:
            baseline = _fit_segment(self.frame, s, end)
            stop, _ = self.hold_end(baseline, s, end)
            if stop >= end or stop - s >= SPAN_MIN_S:
                out.append(SpinSegment(s, stop, baseline, self.seed_dt))
            else:
                stop = self.raw_end(s, end)
                out.append(SpinSegment(s, stop, None, self.raw_seed(s, stop)))
            s = stop
        return out

    def hold_end(
        self,
        baseline: SpinBaseline,
        start: float,
        end: float,
        *,
        at_start: bool = False,
        enough: float = math.inf,
    ) -> tuple[float, float]:
        """`(stop, last)`: the first epoch from `start` on where the residual
        against `baseline` turns too fast (`end` when it holds), and the last
        epoch before it where the check ran and held.

        The walk checks the probes from `start` on, and `start` itself with
        `at_start`. A gap does not end the span, but it is no evidence that
        the baseline holds either. With `enough`, the walk stops at the first
        holding probe at or after it.
        """
        lo = start
        first = int(np.searchsorted(self.probes, start, side="left"))
        epochs = [float(e) for e in self.probes[first:]]
        if at_start and (not epochs or epochs[0] != start):
            epochs.insert(0, start)
        for p in epochs:
            if p >= end:
                break
            ok = self.holds(baseline, p, end)
            if ok is None:
                continue
            if ok:
                lo = p
                if p >= enough:
                    return p, p
                continue
            last, hi = lo, p
            for _ in range(REFINE_ITERS):
                mid = 0.5 * (lo + hi)
                ok = self.holds(baseline, mid, end)
                # A gap at the midpoint counts as holding, so the cut lands at
                # the coverage after it and the next fit has data.
                if ok is False:
                    hi = mid
                else:
                    lo = mid
                    if ok:
                        last = mid
            return hi, last
        return end, lo

    def holds(self, baseline: SpinBaseline, et: float, end: float) -> bool | None:
        """Whether the residual turns at most the alias angle over the seed
        step from `et` (clipped to `end`). None in a gap."""
        turn = _residual_turn(self.frame, baseline, et, min(et + self.seed_dt, end))
        return None if turn is None else turn <= self.alias_angle

    def raw_end(self, start: float, end: float) -> float:
        """Earliest epoch after `start` from which a fitted baseline is seen
        to hold for `SPAN_MIN_S`; `end` when there is none."""

        def good(et: float) -> bool:
            if _omega(self.frame, et) is None:
                return False
            baseline = _fit_segment(self.frame, et, end)
            _, last = self.hold_end(
                baseline, et, end, at_start=True, enough=et + SPAN_MIN_S
            )
            return last - et >= SPAN_MIN_S

        lo, step = start, self.seed_dt
        while start + step < end:
            hi = start + step
            if good(hi):
                while hi - lo > RAW_EDGE_TOL_S:
                    mid = 0.5 * (lo + hi)
                    if good(mid):
                        hi = mid
                    else:
                        lo = mid
                return hi
            lo, step = hi, 2.0 * step
        return end

    def raw_seed(self, start: float, end: float) -> float:
        """Seed step that keeps the raw spin under the alias angle at the
        stretch's top rate."""
        ets = np.arange(start, end - OMEGA_DDT, RATE_SCAN_S)
        omegas = spin_omegas(self.frame, ets)
        top = max(
            (float(np.linalg.norm(o)) for o in omegas if o is not None), default=0.0
        )
        return min(self.seed_dt, self.alias_angle / top) if top > 0 else self.seed_dt


def _residual_turn(
    frame: str, baseline: SpinBaseline, start: float, end: float
) -> float | None:
    """Net turn (rad) of the residual against `baseline` over `[start, end]`;
    None in a gap.

    The sub-steps keep each turn under `SUB_TURN_RAD` for any residual up to
    the spin rate plus the baseline rate. The net turn is the length of the
    summed rotation vectors, so the wobble of a coning spin cancels instead of
    adding up.
    """
    if end - start <= OMEGA_DDT:
        return None
    oa, ob = _omega(frame, start), _omega(frame, end - OMEGA_DDT)
    if oa is None or ob is None:
        return None
    top = max(float(np.linalg.norm(oa)), float(np.linalg.norm(ob)))
    top += baseline.rate_rad_s
    n = max(1, math.ceil((end - start) * top / SUB_TURN_RAD))
    ets = np.linspace(start, end, n + 1)
    try:
        quats = np.array(
            [spiceypy.m2q(spiceypy.pxform("J2000", frame, float(e))) for e in ets]
        )
    except spiceypy.exceptions.SpiceyError:
        return None
    half = 0.5 * baseline.rate_rad_s * (ets - baseline.t0)
    spin = np.column_stack([np.cos(half), np.sin(half)[:, None] * baseline.axis])
    composed = q_mul_rows(spin, baseline.anchor)
    composed[:, 1:] *= -1.0
    residual = q_mul_rows(composed, quats)
    conj = residual[:-1].copy()
    conj[:, 1:] *= -1.0
    steps = q_mul_rows(residual[1:], conj)
    steps[steps[:, 0] < 0] *= -1.0
    sin_half = np.linalg.norm(steps[:, 1:], axis=1)
    angle = 2.0 * np.arctan2(sin_half, steps[:, 0])
    scale = np.divide(angle, sin_half, out=np.zeros_like(angle), where=sin_half > 0)
    return float(np.linalg.norm((steps[:, 1:] * scale[:, None]).sum(axis=0)))


def _fit_segment(frame: str, start: float, end: float) -> SpinBaseline:
    """Fit the span's baseline from a short dense window at its (covered) start."""
    fit_start = _first_covered(frame, start, min(end, start + FIT_SHORT_S))
    window = min(FIT_SHORT_S, end - fit_start)
    n = max(2, int(window * FIT_SHORT_HZ))
    ets = np.linspace(fit_start, fit_start + window, n)
    return fit_spin_baseline(sample_truth(frame, ets), ets, fit_start)


def _first_covered(frame: str, start: float, cap: float, step: float = 60.0) -> float:
    """First epoch ≥ `start` with CK coverage, so a span boundary landing in a
    gap doesn't anchor the fit on repeated-identity samples."""
    et = start
    while et < cap:
        try:
            spiceypy.pxform("J2000", frame, et)
            return et
        except spiceypy.exceptions.SpiceyError:
            et += step
    return start
