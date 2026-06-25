"""Split a spinner's mission into rate-stable spans, one baseline each.

A single constant spin baseline only cancels the spin while rate and axis hold.
Juno steps between 1 and 2 RPM across mission phases, so a mission-wide baseline
leaves a fast residual (the rate error) wherever the phase differs from the one
it was fit on — millions of keyframes. We instead measure the local spin across
the mission, cut at the phase transitions, and fit one `SpinBaseline` per span.

A non-spinner (slow slewing orbiter) returns a single span with no baseline —
its raw motion already samples fine, and an inverse spin would only add
curvature. The spinner test is the same alias gate the extractor used: a turn
wider than the alias angle per seed step aliases the adaptive sampler.
"""

import logging
import math
from dataclasses import dataclass

import numpy as np
import spiceypy

from .baseline import SpinBaseline, fit_spin_baseline
from .quaternion import q_conj, q_mul
from .sample import sample_truth

logger = logging.getLogger(__name__)

# Spin-rate timeline resolution — omega probes spread across the mission. The
# transitions we care about (1↔2 RPM) last months, so a coarse grid finds them.
SEG_MAX_PROBES = 1500
# Close-pair spacing for a local angular-velocity probe (s). Small enough that a
# fast spin turns < 10° between the pair, so the chord tracks the rate.
OMEGA_DDT = 0.5
# New span when the local omega vector departs this fraction from the span's
# running reference — captures both a rate step and an axis reorientation. The
# 1↔2 RPM steps are a 100% change, far above the threshold; in-span jitter is
# a few percent, far below.
SEG_REL_TOL = 0.2
# Don't spawn a span shorter than this — a brief maneuver keeps its neighbour's
# baseline (a few extra keyframes) rather than a sliver segment of its own.
SEG_MIN_S = 6 * 3600.0
# Boundary bisection depth — localises a transition to (probe gap)/2³⁰ ≈ exact,
# so a span never inherits a sliver of the adjacent phase's wrong-rate spin.
REFINE_ITERS = 30
# Short dense fit window: a constant rate fits from sub-degree-spaced samples
# over a few hundred seconds. A long sparse window aliases the fit itself.
FIT_SHORT_S = 600.0
FIT_SHORT_HZ = 20.0


@dataclass(frozen=True)
class SpinSegment:
    """One mission span and the baseline to subtract over it (None = raw)."""

    start_et: float
    end_et: float
    baseline: SpinBaseline | None


def plan_segments(
    frame: str, t0: float, t1: float, *, alias_angle: float, seed_dt: float
) -> list[SpinSegment]:
    """Partition `[t0, t1]` into rate-stable spans, fitting a baseline per span.

    Returns a single raw (baseline-free) span for a non-spinner. For a spinner,
    returns one span per spin phase, each carrying a `SpinBaseline` fit from a
    short dense window at the span's start.
    """
    ets, omegas = _spin_timeline(frame, t0, t1)
    speeds = [float(np.linalg.norm(o)) for o in omegas if o is not None]
    if not speeds or np.median(speeds) * seed_dt <= alias_angle:
        return [SpinSegment(t0, t1, None)]

    cuts = [t0, *_phase_boundaries(frame, ets, omegas), t1]
    segments = [
        SpinSegment(a, b, _fit_segment(frame, a, b)) for a, b in zip(cuts, cuts[1:])
    ]
    if len(segments) > 1:
        logger.info(
            "attitude: %s — %d spin phases at %s RPM",
            frame,
            len(segments),
            ", ".join(
                f"{s.baseline.rate_rad_s / (2 * math.pi) * 60:.1f}"
                if s.baseline
                else "—"
                for s in segments
            ),
        )
    return segments


def _spin_timeline(
    frame: str, t0: float, t1: float
) -> tuple[np.ndarray, list[np.ndarray | None]]:
    """Local angular-velocity vector at each grid point (None in a CK gap)."""
    ets = np.linspace(t0, max(t0, t1 - OMEGA_DDT), SEG_MAX_PROBES)
    return ets, [_omega(frame, float(e)) for e in ets]


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
