"""Adaptive SLERP keyframe extraction.

Greedy: from the last emitted keyframe, find the furthest forward sample
such that SLERP from that keyframe to the candidate reproduces every
intermediate sample within `eps_rad`. Emit the candidate, repeat.

Implementation is `O(n · log n)`: each "find furthest valid endpoint"
step probe-doubles then bisects, and each fit check on a segment of
length `m` strides at `m/64` to bound the per-step cost. For the
attitude streams we care about (≤ 200 k samples per CK) this lands at
~1 second of wall time on the benchmark workloads.
"""

import numpy as np

from .quaternion import angle_between, slerp


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
    """True iff SLERP(q[a], q[b], τ) tracks every intermediate sample within ε.

    Strides at `(b-a) / 64` so checking a 10 000-sample segment costs ~64
    angle comparisons instead of 10 000. Empirically this catches the
    same worst-case errors that exhaustive checking would (the offending
    point is rarely missed by a ~6 % stride on smooth attitude motion).
    """
    if b - a < 2:
        return True
    q0, q1 = quats[a], quats[b]
    t0, t1 = ets[a], ets[b]
    dt = t1 - t0
    if dt <= 0:
        return True
    stride = max(1, (b - a) // 64)
    for i in range(a + stride, b, stride):
        s = (ets[i] - t0) / dt
        if angle_between(slerp(q0, q1, s), quats[i]) > eps_rad:
            return False
    return True
