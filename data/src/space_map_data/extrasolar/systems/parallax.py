"""Whether two points are at one distance.

`same_distance` is El-Badry's test of a bound pair. `parallaxes_disagree` and
`disagree` are the veto: two parallaxes that put two points at clearly
different distances.
"""

import math

import numpy as np

from space_map_data.extrasolar.sky import separation as sky_separation
from space_map_data.extrasolar.systems.resolve import OWN_ASTROMETRY, Fact

# The bound-pair test of El-Badry, Rix & Heintz 2021 (MNRAS 506, 2269),
# section 2, eqs. 1-6, with raw errors. ϖ is the brighter star's parallax.
MIN_PARALLAX_SNR = 5.0
MAX_PARALLAX_ERROR = 2.0
# Eq. 1: θ/arcsec ≤ 206.265 · ϖ/mas, a projected separation of 1 pc.
PARSEC_SEPARATION = 206.265
# Eq. 2: parallaxes within 3σ, or 6σ at 4″ and closer.
CLOSE_SEPARATION = 4.0
WIDE_SIGMA, CLOSE_SIGMA = 3.0, 6.0
# Eqs. 3-6: motions apart by at most 0.44 · ϖ^1.5 · θ^-0.5 mas/yr plus 2σ.
ORBIT_MOTION = 0.44
MOTION_SIGMA = 2.0
# Parallaxes clearly disagree beyond 5σ, or 6σ at CLOSE_SEPARATION and
# closer, and by more than VETO_SHARE of the larger one.
VETO_WIDE_SIGMA, VETO_CLOSE_SIGMA = 5.0, 6.0
VETO_SHARE = 0.1


def same_distance(first: Fact, second: Fact) -> bool:
    """Whether two points pass El-Badry's test of a bound pair."""
    for fact in (first, second):
        if not 0 < fact.parallax_error < MAX_PARALLAX_ERROR:
            return False
        if not fact.parallax / fact.parallax_error > MIN_PARALLAX_SNR:
            return False
    bright = second if second.mag < first.mag else first
    separation = float(sky_separation(first.ra, first.dec, second.ra, second.dec))
    if not 0 < separation <= PARSEC_SEPARATION * bright.parallax:
        return False
    sigma = CLOSE_SIGMA if separation <= CLOSE_SEPARATION else WIDE_SIGMA
    errors = math.hypot(first.parallax_error, second.parallax_error)
    if not abs(first.parallax - second.parallax) < sigma * errors:
        return False
    ra, dec = first.pmra - second.pmra, first.pmdec - second.pmdec
    apart = math.hypot(ra, dec)
    orbit = ORBIT_MOTION * bright.parallax**1.5 / math.sqrt(separation)
    if apart <= orbit:
        return True
    error = (
        math.sqrt(
            (first.pmra_error**2 + second.pmra_error**2) * ra**2
            + (first.pmdec_error**2 + second.pmdec_error**2) * dec**2
        )
        / apart
    )
    return apart <= orbit + MOTION_SIGMA * error


def parallaxes_disagree(
    parallax: np.ndarray,
    error: np.ndarray,
    other: np.ndarray,
    other_error: np.ndarray,
    separation: np.ndarray,
) -> np.ndarray:
    """Whether two measured parallaxes, each over 5σ, clearly disagree."""
    with np.errstate(invalid="ignore"):
        measured = (error > 0) & (other_error > 0)
        measured &= (parallax > MIN_PARALLAX_SNR * error) & (
            other > MIN_PARALLAX_SNR * other_error
        )
        gap = np.abs(parallax - other)
        sigma = np.where(
            separation <= CLOSE_SEPARATION, VETO_CLOSE_SIGMA, VETO_WIDE_SIGMA
        )
        wide = gap > sigma * np.hypot(error, other_error)
        return measured & wide & (gap > VETO_SHARE * np.maximum(parallax, other))


def disagree(first: Fact, second: Fact) -> bool:
    """Whether the own astrometry of two points puts them at two distances."""
    if first.astrometry not in OWN_ASTROMETRY:
        return False
    if second.astrometry not in OWN_ASTROMETRY:
        return False
    separation = float(sky_separation(first.ra, first.dec, second.ra, second.dec))
    return bool(
        parallaxes_disagree(
            np.asarray(first.parallax),
            np.asarray(first.parallax_error),
            np.asarray(second.parallax),
            np.asarray(second.parallax_error),
            np.asarray(separation),
        )
    )
