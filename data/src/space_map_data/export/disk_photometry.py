"""The factor on the lunar weight of McEwen (1996) for a body with a published
disk-resolved fit (`constants/disk_photometry.py`).

The renderer shades airless ground with the lunar-Lambert law
r ∝ 2L µ0/(µ0+µ) + (1-L) µ0, with the lunar weight L(phase) of McEwen for the
Moon. A body with a fit takes L(phase) times one factor. The factor is the
least-squares fit of that product to the published L over the phases of the
fit. A Minnaert fit becomes L by a least-squares fit of the lunar-Lambert law
to the Minnaert disc, area-weighted, as McEwen (1991) fits laws to each other.
"""

from functools import lru_cache

import numpy as np

from space_map_data.constants.disk_photometry import (
    DISK_PHOTOMETRY,
    LunarLambertFit,
    MinnaertFit,
)

# The lunar weight of McEwen (1996) in the phase angle, in degrees.
_MCEWEN_POLY = (-0.019, 0.000242, -0.00000146)
# Below this weight of McEwen the ratio of two weights says little.
_MIN_MCEWEN_WEIGHT = 0.1
# Points of the disc that a fit uses: emission and incidence below these.
_MAX_EMISSION_DEG = 80.0
_MAX_INCIDENCE_DEG = 85.0
_DISC_SAMPLES = 301


def mcewen_lunar_weight(phase_deg: float) -> float:
    """Lunar weight of McEwen (1996): 1 at phase 0, 0 from about 104° on."""
    a, b, c = _MCEWEN_POLY
    p = phase_deg
    return min(1.0, max(0.0, 1 + p * (a + p * (b + p * c))))


def _disc(phase_deg: float) -> tuple[np.ndarray, np.ndarray]:
    """Incidence and emission cosines on a grid even in projected area over
    the lit, visible disc."""
    alpha = np.radians(phase_deg)
    xs = np.linspace(-1, 1, _DISC_SAMPLES)
    x, y = np.meshgrid(xs, xs)
    inside = x**2 + y**2 < 1
    mu = np.sqrt(1 - x[inside] ** 2 - y[inside] ** 2)
    mu0 = x[inside] * np.sin(alpha) + mu * np.cos(alpha)
    keep = (mu > np.cos(np.radians(_MAX_EMISSION_DEG))) & (
        mu0 > np.cos(np.radians(_MAX_INCIDENCE_DEG))
    )
    return mu0[keep], mu[keep]


def minnaert_lunar_weight(k: float, phase_deg: float) -> float:
    """Lunar weight of the lunar-Lambert law that best fits a Minnaert disc."""
    mu0, mu = _disc(phase_deg)
    radiance = mu0**k * mu ** (k - 1)
    terms = np.stack([2 * mu0 / (mu0 + mu), mu0], axis=1)
    (lunar, lambert), *_ = np.linalg.lstsq(terms, radiance, rcond=None)
    return float(lunar / (lunar + lambert))


def published_lunar_weight(
    fit: MinnaertFit | LunarLambertFit, phase_deg: float
) -> float:
    """The lunar weight that the published fit gives at this phase."""
    if isinstance(fit, MinnaertFit):
        return minnaert_lunar_weight(fit.k0 + fit.k1 * phase_deg, phase_deg)
    return min(1.0, max(0.0, fit.c0 + fit.c1 * phase_deg))


def weight_scale(fit: MinnaertFit | LunarLambertFit) -> float:
    """Factor f that makes f * L_McEwen fit the published weight over the
    phases of the fit, in least squares."""
    phases = [
        p
        for p in np.arange(fit.phase_min_deg, fit.phase_max_deg + 0.5, 1.0)
        if mcewen_lunar_weight(p) >= _MIN_MCEWEN_WEIGHT
    ]
    ours = np.array([mcewen_lunar_weight(p) for p in phases])
    theirs = np.array([published_lunar_weight(fit, p) for p in phases])
    return float(np.dot(ours, theirs) / np.dot(ours, ours))


@lru_cache(maxsize=None)
def lunar_weight_scale(object_id: str) -> float | None:
    """Factor on the lunar weight of McEwen for this body, to 3 decimals, or
    None for a body with no published fit."""
    fit = DISK_PHOTOMETRY.get(object_id)
    if fit is None:
        return None
    return round(weight_scale(fit), 3)
