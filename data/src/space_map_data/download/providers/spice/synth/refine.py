"""Cadence policy + Hill-sphere proximity → refinement windows."""

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import spiceypy

from space_map_data.utils.paths import DERIVED_POSITION_DIR, SOURCES_POSITION_DIR

from space_map_data.utils.time import et_to_jd

from .horizons_api import Sample, _jd_to_iso

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

# (secondary_naif, primary_naif) pairs for Hill-radius computation. Outer
# planets use barycenter IDs (4, 5, 6, 7, 8) because de440.bsp only contains
# barycenters past Mars; planet-only mass differs from barycenter by <1%, fine
# for proximity bucketing. Mercury/Venus have no moons so 199/299 == their
# barycenters. Earth and Moon get separate entries (separated by 384 000 km;
# we want to detect proximity to either body, not just to EMB).
_HILL_PAIRS: tuple[tuple[int, int], ...] = (
    (199, 10),
    (299, 10),
    (399, 10),
    (301, 399),
    (4, 10),
    (5, 10),
    (6, 10),
    (7, 10),
    (8, 10),
)

# Sun proximity-refine threshold isn't a Hill radius — the Sun's true Hill is
# the heliopause. We derive a synthetic "Hill" entry from the alias condition
# for a 7-day coarse cadence: at heliocentric distance r the circular-orbit
# velocity is sqrt(GM_sun/r), and one coarse step covers a chord v×dt. We want
# to refine wherever chord ≥ _SUN_REFINE_CHORD_TO_R × r — i.e., the spacecraft
# sweeps ~30°+ per coarse sample, beyond which Hermite-degree-7 between samples
# diverges from the true trajectory (PSP perihelion rendered at 3 R_sun vs the
# real 9.85 R_sun). Stored pre-divided by REFINE_HILL_FACTOR so the scaling in
# `_identify_refinement_windows` reproduces the trigger distance directly.
_SUN_REFINE_CHORD_TO_R = 0.5
_COARSE_STEP_S = 7 * 86400.0


def _gm_table_km3_s2() -> dict[int, float]:
    """Read gm.csv → {naif_id: GM (km³/s²)}. Path matches export.systems.load_gms."""
    out: dict[int, float] = {}
    with (DERIVED_POSITION_DIR / "tables" / "gm.csv").open(newline="") as f:
        for row in csv.DictReader(f):
            out[int(row["naif_id"])] = float(row["gm_km3_s2"])
    return out


_HILL_CACHE: dict[int, float] | None = None


def compute_major_body_hill_km() -> dict[int, float]:
    """Compute Hill radii (km) for the proximity-refine check.

    Planet/Moon: r_hill = a × ∛(GM_s / 3 GM_p) where `a` comes from a J2000
    osculating-element snapshot via SPICE. Caller must furnish LSK + de440
    before invoking — `cache.py` already does this around _identify_refinement_windows.

    Sun: synthetic "Hill" = r_trigger / REFINE_HILL_FACTOR where r_trigger is
    the heliocentric distance at which the per-coarse-step chord equals
    `_SUN_REFINE_CHORD_TO_R × r` for a circular orbit. With the default 0.5
    ratio and 7-day cadence this comes out at ~12 Mkm (×5 = 58 Mkm trigger,
    catching PSP's pre/post-perihelion coarse samples).

    Cached on first call — values are stable across the pipeline run.
    """
    global _HILL_CACHE
    if _HILL_CACHE is not None:
        return _HILL_CACHE
    gm = _gm_table_km3_s2()
    et = spiceypy.utc2et("2000-01-01T12:00:00")
    out: dict[int, float] = {}
    for secondary, primary in _HILL_PAIRS:
        state, _ = spiceypy.spkezr(str(secondary), et, "J2000", "NONE", str(primary))
        elts = spiceypy.oscelt(state, et, gm[primary])
        rp, ecc = elts[0], elts[1]
        a = rp / (1 - ecc) if ecc < 1 else rp
        out[secondary] = a * (gm[secondary] / (3 * gm[primary])) ** (1 / 3)
    r_trigger = (
        gm[10] * _COARSE_STEP_S * _COARSE_STEP_S / _SUN_REFINE_CHORD_TO_R**2
    ) ** (1 / 3)
    out[10] = r_trigger / REFINE_HILL_FACTOR
    _HILL_CACHE = out
    logger.info(
        "computed hill radii (Mkm): %s",
        ", ".join(f"{b}={r / 1e6:.2f}" for b, r in sorted(out.items())),
    )
    return out


def _identify_refinement_windows(
    samples: list[Sample],
    get_body_pos,
    *,
    coverage_start_iso: str,
    coverage_end_iso: str,
    hill_table: dict[int, float],
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
        for body_id, hill_km in hill_table.items():
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
        a_jd = et_to_jd(samples[i].et) - REFINE_PAD_DAYS
        b_jd = et_to_jd(samples[j - 1].et) + REFINE_PAD_DAYS
        a = max(cov_start, datetime.fromisoformat(_jd_to_iso(a_jd)).date())
        b = min(cov_end, datetime.fromisoformat(_jd_to_iso(b_jd)).date())
        if a < b:
            windows.append((a.isoformat(), b.isoformat()))
        i = j
    return windows


def _furnish_planets() -> list[Path]:
    """Furnish lsk + de440 so spkpos can return planet positions. Returns the
    paths so the caller can `spiceypy.unload` them when done."""
    kernels_root = SOURCES_POSITION_DIR / "spice-kernels"
    paths = [
        kernels_root / "lsk" / "naif0012.tls",
        kernels_root / "spk" / "planets" / "de440.bsp",
    ]
    for p in paths:
        spiceypy.furnsh(str(p))
    return paths
