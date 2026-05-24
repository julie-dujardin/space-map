"""Cadence policy + Hill-sphere proximity → refinement windows."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import spiceypy

from space_map_data.utils.paths import DOWNLOAD_DIR

from .horizons_api import Sample, _et_to_jd, _jd_to_iso

logger = logging.getLogger(__name__)

REFINE_STEP = "1 h"

# Probes whose orbital period inside a major body's Hill sphere is comparable
# to or shorter than `REFINE_STEP`. SPK Type 13 uses degree-7 Hermite
# interpolation across (typically) 8 consecutive samples — at 1-hour cadence
# that polynomial spans 8 hours, which for a ~2-hour lunar orbiter covers
# 4 orbital cycles. The polynomial can't represent that, so spkpos between
# samples returns ~hundreds-of-km errors with samples dipping below the
# Moon's surface. Bumping these probes to 1-minute cadence keeps the
# polynomial span at ~8 minutes (well under one orbit) so Hermite is clean.
#
# Only includes probes for which we don't have an agency-published SPK and
# whose lunar / planetary orbit is dense enough to alias. Membership checked
# in `_refine_step_for`.
TIGHT_REFINE_NAIF_IDS: frozenset[int] = frozenset(
    {
        # Lunar low orbiters (~2h period)
        -86,  # Chandrayaan-1
        -152,  # Chandrayaan-2 Orbiter
        -153,  # Chandrayaan-2 Lander (descent)
        -155,  # Danuri / KPLO
        -158,  # Chandrayaan-3 Lander (descent)
        -169,  # Chandrayaan-3 Propulsion Module
        -240,  # SLIM (lunar low orbit + landing)
        # Mars cruise/landing with periapsis ~36min
        -530,  # Mars Pathfinder
        # Earth-LEO satellites with multi-decade coverage are deferred for
        # now — their 1-h SPK cadence aliases the same way, but they render
        # close enough to Earth that the 1-h-Hermite jitter isn't visible at
        # the zoom levels we care about, and a full 1-min refetch is multi-
        # hour per probe. Re-add (-163 WISE, -127424 Aqua, -128376 Aura,
        # -128485 Swift, etc.) once the writer can handle very-long-coverage
        # tight refines incrementally.
    }
)


def _refine_step_for(naif_id: int) -> str:
    """Refinement cadence for `naif_id`. 1-minute for fast-period orbits
    flagged in `TIGHT_REFINE_NAIF_IDS`, else the default `REFINE_STEP`."""
    if naif_id in TIGHT_REFINE_NAIF_IDS:
        return "1 m"
    return REFINE_STEP


def _coarse_step_for(span_days: int) -> str:
    """Pick a coarse-pass cadence that yields ≥ degree+1=8 samples while
    keeping the response small for long-lived spacecraft. Voyager-class
    decades-long missions get 7d; ~year missions get 1d; sub-2-month
    missions go straight to 1h and skip the refinement pass entirely."""
    if span_days <= 60:
        return "1 h"
    if span_days <= 365:
        return "1 d"
    return "7 d"


# Within this many Hill radii of any major body → refine to REFINE_STEP.
REFINE_HILL_FACTOR = 5.0
# Pad each refinement window so the approach and departure tails are
# resampled at the tight cadence too (avoids sharp 7d→1h transitions).
REFINE_PAD_DAYS = 7.0

# Major-body NAIF IDs and Hill-sphere radii in km. We use planet *barycenter*
# NAIF IDs for the outer planets (4, 5, 6, 7, 8) because de440.bsp only
# contains the barycenters of Mars onwards, not the planet bodies themselves
# (which need the per-system satellite kernels). The barycenter coincides
# with the planet to within a few thousand km for the outer planets — fine
# for proximity-bucket detection. Mercury/Venus barycenter == the planet
# itself (no moons) so we use 199 and 299 directly. Earth and Moon get their
# own IDs because they're separated by ~384 000 km and we want to detect
# proximity to either body, not just to the Earth-Moon barycenter.
MAJOR_BODY_HILL_KM: dict[int, float] = {
    199: 2.20e5,  # Mercury
    299: 1.01e6,  # Venus
    399: 1.50e6,  # Earth
    301: 6.61e4,  # Moon (Earth-centred Hill sphere)
    4: 1.08e6,  # Mars barycenter
    5: 5.31e7,  # Jupiter barycenter
    6: 6.50e7,  # Saturn barycenter
    7: 7.00e7,  # Uranus barycenter
    8: 1.16e8,  # Neptune barycenter
}


def _identify_refinement_windows(
    samples: list[Sample],
    get_body_pos,
    *,
    coverage_start_iso: str,
    coverage_end_iso: str,
) -> list[tuple[str, str]]:
    """Coarse samples + per-body Hill-radius proximity check → 1h windows.

    `get_body_pos(naif_id, et)` returns the body's SSB-relative position (km).
    Returned (start, end) iso pairs are clamped to the spacecraft's coverage
    window minus a 1-day margin so Horizons doesn't reject the fetch as
    out-of-coverage.
    """
    if not samples:
        return []
    cov_start = datetime.fromisoformat(coverage_start_iso).date() + timedelta(days=1)
    cov_end = datetime.fromisoformat(coverage_end_iso).date() - timedelta(days=1)
    n = len(samples)
    near = np.zeros(n, dtype=bool)
    for i, s in enumerate(samples):
        spc = np.asarray(s.state[:3])
        for body_id, hill_km in MAJOR_BODY_HILL_KM.items():
            try:
                body_pos = np.asarray(get_body_pos(body_id, s.et))
            except spiceypy.exceptions.SpiceyError:
                continue
            if np.linalg.norm(spc - body_pos) < REFINE_HILL_FACTOR * hill_km:
                near[i] = True
                break

    windows: list[tuple[str, str]] = []
    i = 0
    while i < n:
        if not near[i]:
            i += 1
            continue
        j = i
        while j < n and near[j]:
            j += 1
        a_jd = _et_to_jd(samples[i].et) - REFINE_PAD_DAYS
        b_jd = _et_to_jd(samples[j - 1].et) + REFINE_PAD_DAYS
        a = max(cov_start, datetime.fromisoformat(_jd_to_iso(a_jd)).date())
        b = min(cov_end, datetime.fromisoformat(_jd_to_iso(b_jd)).date())
        if a < b:
            windows.append((a.isoformat(), b.isoformat()))
        i = j
    return windows


def _furnish_planets() -> list[Path]:
    """Furnish lsk + de440 so spkpos can return planet positions. Returns the
    paths so the caller can `spiceypy.unload` them when done."""
    kernels_root = DOWNLOAD_DIR / "spice" / "kernels"
    paths = [
        kernels_root / "lsk" / "naif0012.tls",
        kernels_root / "spk" / "planets" / "de440.bsp",
    ]
    for p in paths:
        spiceypy.furnsh(str(p))
    return paths
