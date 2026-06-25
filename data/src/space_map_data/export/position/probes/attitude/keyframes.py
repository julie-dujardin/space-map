"""Adaptive SLERP keyframe extraction.

Greedy: from the last emitted keyframe, find the furthest forward sample
such that SLERP from that keyframe to the candidate reproduces every
intermediate sample within `eps_rad`. Emit the candidate, repeat.

Each "find furthest valid endpoint" step probe-doubles then bisects, and
the fit check is an exact vectorised SLERP comparison over the (already
sparse) sample stream. Operates on the adaptive-sampler output, so the
input is thousands of samples per window, not millions.
"""

import math

import numpy as np

# A pure constant-axis spin is an exact SLERP geodesic, so the greedy walker
# would extend one keyframe segment indefinitely — until it spans ≥ 180°, where
# SLERP can no longer tell the short arc from the long one and reconstructs the
# wrong way (a clean slow spinner like Gaia flips ~180° mid-segment). Cap the
# per-segment angle well below π so the short arc is always unambiguous.
MAX_SEGMENT_ANGLE_RAD = math.radians(90.0)


def extract_keyframes(quats: np.ndarray, ets: np.ndarray, eps_rad: float) -> list[int]:
    """Return the list of sample indices to keep as SLERP keyframes."""
    n = quats.shape[0]
    if n == 0:
        return []
    kf = [0]
    last = 0
    while last < n - 1:
        hi = last + 1
        # Probe-double until we overshoot — the first failing endpoint
        # bounds the bisection range.
        while hi < n - 1:
            r = min(n - 1, last + 2 * (hi - last))
            if not _segment_fits(quats, ets, last, r, eps_rad):
                break
            hi = r
        good = hi
        r_high = min(n - 1, last + 2 * (hi - last))
        bad = (
            r_high
            if r_high > good and not _segment_fits(quats, ets, last, r_high, eps_rad)
            else n - 1
        )
        while bad - good > 1:
            mid = (good + bad) // 2
            if _segment_fits(quats, ets, last, mid, eps_rad):
                good = mid
            else:
                bad = mid
        kf.append(good)
        last = good
    return kf


def _segment_fits(
    quats: np.ndarray, ets: np.ndarray, a: int, b: int, eps_rad: float
) -> bool:
    """True iff SLERP(q[a], q[b], τ) tracks *every* intermediate sample within ε.

    Checks all enclosed samples (vectorised SLERP), not a stride — a coarse
    stride aliases slow precession, accepting an over-long geodesic that fits
    the probed points but deviates tens of degrees between them. The sample
    stream is already adaptively sparse, so an exact check stays cheap.
    """
    if b - a < 2:
        return True
    q0, q1 = quats[a], quats[b]
    t0, dt = ets[a], ets[b] - ets[a]
    if dt <= 0:
        return True
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    # Reject a segment spanning past the unambiguous short-arc regime, even if
    # the geodesic happens to track the samples — SLERP would flip at decode.
    if 2.0 * math.acos(min(1.0, d)) > MAX_SEGMENT_ANGLE_RAD:
        return False
    s = (ets[a + 1 : b] - t0) / dt
    if d > 0.9995:
        interp = q0 + s[:, None] * (q1 - q0)
    else:
        th0 = math.acos(d)
        sin0 = math.sin(th0)
        interp = (np.sin((1 - s) * th0) / sin0)[:, None] * q0 + (
            np.sin(s * th0) / sin0
        )[:, None] * q1
    interp /= np.linalg.norm(interp, axis=1, keepdims=True)
    dots = np.abs(np.sum(interp * quats[a + 1 : b], axis=1))
    max_angle = 2.0 * math.acos(min(1.0, float(dots.min())))
    return max_angle <= eps_rad
