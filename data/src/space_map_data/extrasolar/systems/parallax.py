"""Whether two points are at one distance, and whether they can be bound.

`same_distance` is El-Badry's test of a bound pair. `parallaxes_disagree` and
`disagree` are the veto: two parallaxes that put two points at clearly
different distances, with the error of a Gaia solution that does not fit its
star scaled by its RUWE (`veto_error`). `unbound` refutes a pair by its
projected width, by its motion, or as neighbours in one star cluster.
`wrong_object` tells which way a refuted pair goes: it never refutes a pair
itself, because real wide pairs can have rough separations.
"""

import math

import numpy as np

from space_map_data.extrasolar.sky import separation as sky_separation
from space_map_data.extrasolar.systems.resolve import (
    GAIA_ASTROMETRY,
    HIPPARCOS_ASTROMETRY,
    OWN_ASTROMETRY,
    Fact,
)

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
# A Gaia solution over this RUWE does not fit its star, and its errors are too
# small. Scaled by the RUWE, the vetoes that go agree in RV 65% of the time, and
# the ones that stay 12%. Skipping every veto over this RUWE frees 50%.
MAX_RUWE = 1.4
# The scale stops here. On pairs that RV shows real, a parallax gap stops growing
# with the RUWE at about 3 raw errors. Pairs that a stop at 4 refutes agree in RV
# 14% of the time, the chance level, and a stop at 3 refutes ρ Ori and δ Ser.
MAX_SCALE = 4.0
# The tidal radius of 2 M☉ is 1.7 pc (Jiang & Tremaine 2010).
MAX_PARSEC = 2.0
# km/s beyond an orbit plus EXCESS_SIGMA. Gaia radial velocities agree in 41%
# of pairs at 6-8 km/s and 26% at 8-12, against 87% in El-Badry's sample.
MAX_EXCESS = 8.0
EXCESS_SIGMA = 3.0
# km/s for 1 mas/yr at 1 kpc.
KMS = 4.74047
# AU, for two members of one star cluster. G·M/σ² for a pair is 8,000-12,000 AU
# in M67, Praesepe and the Pleiades, and 84-90% of member pairs at 10,000-18,000
# AU are chance.
MAX_CLUSTER_AU = 10_000.0
MAX_CLUSTER_PARSEC = MAX_CLUSTER_AU / (1000 * PARSEC_SEPARATION)
WIDE = f"wider than {MAX_PARSEC} pc"
MOTION = f"moves apart at {MAX_EXCESS} km/s or more"
IN_CLUSTER = f"wider than {MAX_CLUSTER_AU:,.0f} AU in one cluster"
# A listed separation from here up is a catalogue overflow, not a measure.
OVERFLOW = 999.0
# A measured separation this far above the listed one is another object.
WRONG_RATIO = 5.0
WRONG_ARCSEC = 60.0


def same_distance(first: Fact, second: Fact) -> bool:
    """Whether two points pass El-Badry's test of a bound pair."""
    for fact in (first, second):
        if not 0 < fact.parallax_error < MAX_PARALLAX_ERROR:
            return False
        if not fact.parallax / fact.parallax_error > MIN_PARALLAX_SNR:
            return False
    bright = _brighter(first, second)
    separation = _apart(first, second)
    if not 0 < separation <= PARSEC_SEPARATION * bright.parallax:
        return False
    sigma = CLOSE_SIGMA if separation <= CLOSE_SEPARATION else WIDE_SIGMA
    errors = math.hypot(first.parallax_error, second.parallax_error)
    if not abs(first.parallax - second.parallax) < sigma * errors:
        return False
    apart, error = _motions_apart(first, second)
    orbit = ORBIT_MOTION * bright.parallax**1.5 / math.sqrt(separation)
    if apart <= orbit:
        return True
    return apart <= orbit + MOTION_SIGMA * error


def _brighter(first: Fact, second: Fact) -> Fact:
    return second if second.mag < first.mag else first


def _apart(first: Fact, second: Fact) -> float:
    """The separation of two points in arcsec."""
    return float(sky_separation(first.ra, first.dec, second.ra, second.dec))


def _motions_apart(first: Fact, second: Fact) -> tuple[float, float]:
    """How far apart two proper motions are in mas/yr, and its error."""
    ra, dec = first.pmra - second.pmra, first.pmdec - second.pmdec
    apart = math.hypot(ra, dec)
    if not apart > 0:
        return apart, math.nan
    error = (
        math.sqrt(
            (first.pmra_error**2 + second.pmra_error**2) * ra**2
            + (first.pmdec_error**2 + second.pmdec_error**2) * dec**2
        )
        / apart
    )
    return apart, error


def veto_error(error: np.ndarray, ruwe: np.ndarray) -> np.ndarray:
    """The error that the veto and the motion test read."""
    with np.errstate(invalid="ignore"):
        return np.where(ruwe > MAX_RUWE, error * np.minimum(ruwe, MAX_SCALE), error)


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
    return bool(
        parallaxes_disagree(
            np.asarray(first.parallax),
            veto_error(np.asarray(first.parallax_error), np.asarray(first.ruwe)),
            np.asarray(second.parallax),
            veto_error(np.asarray(second.parallax_error), np.asarray(second.ruwe)),
            np.asarray(_apart(first, second)),
        )
    )


def parsecs(first: Fact, second: Fact) -> float:
    """The distance of a pair: its brighter star's, else either star's."""
    for fact in (_brighter(first, second), first, second):
        if math.isfinite(fact.distance) and fact.distance > 0:
            return fact.distance
        if fact.parallax > 0 and fact.parallax > MIN_PARALLAX_SNR * fact.parallax_error:
            return 1000 / fact.parallax
    return math.nan


def projected(first: Fact, second: Fact) -> float:
    """The projected width of a pair in pc."""
    return _apart(first, second) * parsecs(first, second) / (1000 * PARSEC_SEPARATION)


def _has_motion(fact: Fact) -> bool:
    """Whether the motion of a point can refute a pair. A Hipparcos star with
    no 5σ parallax has no distance to turn its motion into km/s."""
    if fact.astrometry in HIPPARCOS_ASTROMETRY:
        return fact.parallax > MIN_PARALLAX_SNR * fact.parallax_error
    return fact.astrometry in GAIA_ASTROMETRY


def excess(first: Fact, second: Fact) -> float:
    """km/s by which two points move apart beyond an orbit plus 3σ, NaN when
    unknown. Gaia's motions are not reliable under CLOSE_SEPARATION."""
    if not (_has_motion(first) and _has_motion(second)):
        return math.nan
    distance = parsecs(first, second)
    separation = _apart(first, second)
    apart, error = _motions_apart(first, second)
    if not (math.isfinite(distance) and separation >= CLOSE_SEPARATION and apart > 0):
        return math.nan
    orbit = ORBIT_MOTION * (1000 / distance) ** 1.5 / math.sqrt(separation)
    return KMS * (apart - orbit - EXCESS_SIGMA * error) * distance / 1000


def unbound(
    first: Fact, second: Fact, moving: bool = True, cluster: bool = False
) -> str | None:
    """Why two points are no bound pair, else None. `moving` is False where
    an orbit or a close pair explains their motions. `cluster` is True for
    two members of one star cluster with no orbit: their shared motion shows
    nothing, as every member has it."""
    width = projected(first, second)
    if width > MAX_PARSEC:
        return WIDE
    if moving and excess(first, second) > MAX_EXCESS:
        return MOTION
    if cluster and width > MAX_CLUSTER_PARSEC:
        return IN_CLUSTER
    return None


def one_cluster(
    clusters: dict[int, frozenset[str]], first: Fact, second: Fact
) -> frozenset[str]:
    """The star clusters that hold both points."""
    none: frozenset[str] = frozenset()
    return clusters.get(first.key, none) & clusters.get(second.key, none)


def cluster_text(clusters: dict[int, frozenset[str]], first: Fact, second: Fact) -> str:
    """The width of a pair in AU, in its star clusters."""
    width = projected(first, second) * 1000 * PARSEC_SEPARATION
    return (
        f"{width:,.0f} AU in {', '.join(sorted(one_cluster(clusters, first, second)))}"
    )


def wrong_object(first: Fact, second: Fact, listed: float | None) -> bool:
    """Whether the points are far from the catalogue's separation of the pair,
    so that one of them is not the star that it lists."""
    if not listed or listed <= 0 or listed >= OVERFLOW:
        return False
    apart = _apart(first, second)
    return apart > WRONG_RATIO * listed and apart - listed > WRONG_ARCSEC
