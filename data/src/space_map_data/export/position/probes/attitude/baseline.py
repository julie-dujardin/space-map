"""Constant-axis constant-rate spin-baseline fit + residual subtraction.

For spin-stabilised spacecraft (e.g. Juno) and nadir-pointed orbiters
where the body-frame rotation is dominated by orbital motion (e.g. MRO),
much of the attitude trace is a simple rotation about a fixed axis at
a fixed rate. Subtracting that motion before keyframe extraction makes
the residual nearly constant — turning 1000s of keyframes into single
digits.

The decision to apply the baseline is data-driven: we always *fit* a
baseline from the median angular velocity, but the writer applies it
only when the residual stream is angularly tighter than the raw stream.
This catches missions where the spin model genuinely simplifies the
signal and skips it for those where it doesn't (e.g. Cassini's
encounter-driven attitude).
"""

import math

import numpy as np

from .quaternion import angle_between, angular_velocity, q_conj, q_mul


def fit_spin_baseline(
    quats: np.ndarray, ets: np.ndarray, *, n_probe_samples: int = 1000
) -> tuple[np.ndarray, float, np.ndarray]:
    """Estimate (axis, rate, anchor) such that q ≈ q_baseline(t) · q_anchor.

    `axis` is the unit rotation axis in J2000; `rate` is the rate in rad/s;
    `anchor` is the first sample (the "phase zero" of the spin).

    Uses the *median* angular velocity over the first `n_probe_samples`
    samples — robust to off-nominal outliers (momentum dumps, brief
    pointing excursions) which would skew a mean.
    """
    n = min(n_probe_samples, quats.shape[0])
    omegas = np.array([angular_velocity(quats, ets, i) for i in range(n)])
    om_med = np.median(omegas, axis=0)
    rate = float(np.linalg.norm(om_med))
    axis = om_med / rate if rate > 1e-9 else np.array([0.0, 0.0, 1.0])
    return axis, rate, quats[0].copy()


def baseline_quaternion(axis: np.ndarray, rate: float, t_seconds: float) -> np.ndarray:
    """exp((rate · t / 2) · axis) — rotation by angle `rate·t` about `axis`."""
    half = rate * t_seconds / 2.0
    return np.array([math.cos(half), *(math.sin(half) * axis)])


def apply_baseline(
    quats: np.ndarray,
    ets: np.ndarray,
    axis: np.ndarray,
    rate: float,
    anchor: np.ndarray,
    *,
    t0: float | None = None,
) -> np.ndarray:
    """Compute the residual stream q_r = q_baseline⁻¹ · q for every sample.

    Decoder reconstruction is q = q_baseline · q_r — so this is the
    composition the writer wants. Continuous sign canonicalisation is
    re-applied (the multiplication can hop to the antipodal representation).

    `t0` is the spin phase-zero epoch (ET seconds) — pass the mission-global
    start so per-file segments share one phase. Defaults to `ets[0]`.
    """
    epoch = float(ets[0]) if t0 is None else t0
    n = quats.shape[0]
    out = np.empty_like(quats)
    last = np.array([1.0, 0.0, 0.0, 0.0])
    for i in range(n):
        t = float(ets[i]) - epoch
        b = q_mul(baseline_quaternion(axis, rate, t), anchor)
        r = q_mul(q_conj(b), quats[i])
        if np.dot(r, last) < 0:
            r = -r
        out[i] = r
        last = r
    return out


def stream_p95_angle_from_identity(quats: np.ndarray) -> float:
    """p95 rotation angle (radians) of each sample from the identity quaternion.

    Used by the writer to decide whether the spin-baseline residual is
    tighter than the raw stream — if it is, we ship the residual.
    """
    sub = quats[::100] if quats.shape[0] > 1000 else quats
    angles = np.array([angle_between(q, np.array([1.0, 0.0, 0.0, 0.0])) for q in sub])
    return float(np.percentile(angles, 95))
