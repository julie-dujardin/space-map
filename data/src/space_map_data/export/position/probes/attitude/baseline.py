"""Constant-axis constant-rate spin-baseline fit + residual subtraction.

A fast spin-stabilised spacecraft (e.g. Juno) turns far enough between
samples to alias the adaptive sampler. We fit the spin from the median
angular velocity and subtract it, so the sampler keyframes the slow
residual instead.

A single constant baseline only holds while the spin is steady; Juno changes
rate across mission phases (1 ↔ 2 RPM), so `segments.py` splits the mission
into rate-stable spans and fits one `SpinBaseline` per span. The rate must be
fit from a *short dense* window — a long window sampled sparsely aliases the
fit itself, leaving a residual that beats at the rate error.
"""

import math
from dataclasses import dataclass

import numpy as np

from .quaternion import angular_velocity, q_conj, q_mul


def baseline_quaternion(axis: np.ndarray, rate: float, t_seconds: float) -> np.ndarray:
    """exp((rate · t / 2) · axis) — rotation by angle `rate·t` about `axis`."""
    half = rate * t_seconds / 2.0
    return np.array([math.cos(half), *(math.sin(half) * axis)])


@dataclass(frozen=True)
class SpinBaseline:
    """One rate-stable spin span's baseline: q ≈ q_spin(t − t0) · anchor.

    `axis`/`rate_rad_s` are the fitted constant spin; `anchor` is the attitude
    at `t0` (the span's phase-zero ET). The decoder reconstructs full attitude
    as `compose(t) · residual`, so the writer stores `residual(t, q)`.
    """

    axis: np.ndarray
    rate_rad_s: float
    anchor: np.ndarray
    t0: float

    def compose(self, et: float) -> np.ndarray:
        """The baseline attitude `q_spin(et − t0) · anchor` at `et`."""
        return q_mul(
            baseline_quaternion(self.axis, self.rate_rad_s, et - self.t0), self.anchor
        )

    def residual(self, et: float, q: np.ndarray) -> np.ndarray:
        """The slow residual `compose(et)⁻¹ · q` the keyframer encodes."""
        return q_mul(q_conj(self.compose(et)), q)


def fit_spin_baseline(quats: np.ndarray, ets: np.ndarray, t0: float) -> SpinBaseline:
    """Fit a `SpinBaseline` from a short dense sample run.

    `axis` is the unit rotation axis; `rate` is the median local rate (rad/s),
    robust to off-nominal outliers (momentum dumps) a mean would chase. `t0` is
    the span's phase-zero epoch; `anchor = quats[0]` must be the attitude there.

    Pass a *dense* window (sub-degree per sample) — a coarse one aliases the
    central-difference angular velocity and biases the rate low.
    """
    omegas = np.array([angular_velocity(quats, ets, i) for i in range(quats.shape[0])])
    om_med = np.median(omegas, axis=0)
    rate = float(np.linalg.norm(om_med))
    axis = om_med / rate if rate > 1e-9 else np.array([0.0, 0.0, 1.0])
    return SpinBaseline(axis=axis, rate_rad_s=rate, anchor=quats[0].copy(), t0=t0)
