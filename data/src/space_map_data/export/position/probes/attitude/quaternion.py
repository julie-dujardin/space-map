"""Quaternion math used by the attitude extractor.

Convention: SPICE-flavoured `(w, x, y, z)`, unit norm, sandwich rotation
(`v_rotated = q · v · q⁻¹`). Sign canonicalisation (qw ≥ 0 and continuous
between adjacent samples) is the caller's responsibility — `sample.py`
handles that since it owns the time series.
"""

import math

import numpy as np


def q_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Hamilton product `a · b`. Composes rotations right-to-left."""
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array(
        [
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        ]
    )


def q_conj(q: np.ndarray) -> np.ndarray:
    """Conjugate (inverse for unit quaternions)."""
    return np.array([q[0], -q[1], -q[2], -q[3]])


def slerp(q0: np.ndarray, q1: np.ndarray, t: float) -> np.ndarray:
    """Spherical linear interpolation at fraction `t` ∈ [0, 1]."""
    d = float(np.dot(q0, q1))
    if d < 0:
        q1 = -q1
        d = -d
    if d > 0.9995:
        # Quaternions are nearly identical; linear interp + renorm avoids the
        # sin(0)/sin(0) blow-up in the great-arc formula. Same numeric guard
        # the renderer needs to use for short-segment SLERP.
        out = q0 + t * (q1 - q0)
        return out / np.linalg.norm(out)
    th0 = math.acos(d)
    s0 = math.sin((1 - t) * th0) / math.sin(th0)
    s1 = math.sin(t * th0) / math.sin(th0)
    return s0 * q0 + s1 * q1


def angle_between(a: np.ndarray, b: np.ndarray) -> float:
    """Smallest rotation angle between two unit quaternions, in radians."""
    return 2.0 * math.acos(min(1.0, abs(float(np.dot(a, b)))))


def angular_velocity(quats: np.ndarray, ets: np.ndarray, i: int) -> np.ndarray:
    """Central-difference angular velocity at index `i`, J2000 frame, rad/s.

    Uses dq/dt = ½ · ω · q so ω = 2 · (dq/dt) · q⁻¹ (vector part).
    """
    j0 = max(0, i - 1)
    j1 = min(quats.shape[0] - 1, i + 1)
    dt = ets[j1] - ets[j0]
    if dt <= 0:
        return np.zeros(3)
    dq = (quats[j1] - quats[j0]) / dt
    return (2.0 * q_mul(dq, q_conj(quats[i])))[1:]
