"""Constant-axis constant-rate spin-baseline fit + residual subtraction.

A fast spin-stabilised spacecraft (e.g. Juno) turns far enough between
samples to alias the adaptive sampler. We fit the spin from the median
angular velocity and subtract it, so the sampler keyframes the slow
residual instead. The writer applies this only when the fitted rate is
fast enough to alias (see `ALIAS_ANGLE_RAD` in `extractor`); slower
motion samples fine raw.
"""

import math

import numpy as np

from .quaternion import angular_velocity, q_conj, q_mul


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
