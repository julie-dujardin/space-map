"""Walk a probe's SPK coverage and emit which zone(s) it's in over time.

Coarse cadence — we don't need second-by-second resolution. Sampling at
day-scale catches zone transitions to within a day, which is below every
zone's chunk size. A probe is in `interplanetary` always *and* in any
planetary zone it falls inside (dupe is intentional, see `zones.py`).
"""

import logging
from dataclasses import dataclass

import numpy as np
import spiceypy

from space_map_data.probes.zones import (
    INTERPLANETARY,
    PLANETARY_ZONES,
)

logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0


@dataclass(frozen=True)
class ZoneInterval:
    zone_key: str
    start_et: float
    end_et: float


# Bodies we check for "is this probe sitting on this body's surface".
# Major planets + Moon (NAIF 301) + a few large moons that have been landed on.
_LANDING_TARGETS: tuple[int, ...] = (
    199,  # Mercury
    299,  # Venus
    301,  # Moon
    399,  # Earth (atmospheric probes / surface bases like Apollo splashdown)
    499,  # Mars
    606,  # Titan (Huygens)
)


def is_landed_probe(
    naif_id: int, kernel_paths: list[str], altitude_threshold_km: float = 50.0
) -> tuple[bool, int | None]:
    """Detect probes that spend their whole coverage parked on a body's surface.

    Heuristic: sample the probe's state at a handful of times across its
    coverage. If at every sample its altitude above some major body is
    below `altitude_threshold_km`, treat it as landed. Returns
    `(True, landing_body_naif_id)` or `(False, None)`.

    Atmospheric / descent probes that crash within hours (Pioneer Venus
    probes, Huygens) are deliberately *not* skipped — their kernels cover
    the entry phase which is real trajectory data. Returns False unless
    every sample is at the surface.
    """
    cov = _coverage(naif_id, kernel_paths)
    if cov is None:
        return False, None
    n_samples = 5
    sample_ets = np.linspace(cov[0] + 60, cov[1] - 60, n_samples)

    # For each candidate body, count how many samples are within altitude.
    counts: dict[int, int] = {}
    for et in sample_ets:
        for body_naif in _LANDING_TARGETS:
            try:
                state, _ = spiceypy.spkezr(
                    str(naif_id), float(et), "ECLIPJ2000", "NONE", str(body_naif)
                )
            except spiceypy.exceptions.SpiceyError:
                continue
            dist = float(np.linalg.norm(state[:3]))
            try:
                radii = spiceypy.bodvrd(str(body_naif), "RADII", 3)[1]
            except spiceypy.exceptions.SpiceyError:
                continue
            r_max = float(max(radii))
            if (dist - r_max) < altitude_threshold_km:
                counts[body_naif] = counts.get(body_naif, 0) + 1
                break  # one body match per sample is enough
    if not counts:
        return False, None
    best_body, best_n = max(counts.items(), key=lambda kv: kv[1])
    if best_n == n_samples:
        return True, best_body
    return False, None


def _coverage(naif_id: int, kernel_paths: list[str]) -> tuple[float, float] | None:
    """Longest contiguous covered interval for `naif_id` across all kernels."""
    intervals: list[tuple[float, float]] = []
    for path in kernel_paths:
        try:
            cell = spiceypy.cell_double(2000)
            spiceypy.spkcov(path, naif_id, cell)
            for i in range(0, spiceypy.wncard(cell)):
                s, e = spiceypy.wnfetd(cell, i)
                intervals.append((s, e))
        except spiceypy.exceptions.SpiceyError:
            continue
    if not intervals:
        return None
    intervals.sort()
    merged: list[list[float]] = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    longest = max(merged, key=lambda iv: iv[1] - iv[0])
    return longest[0], longest[1]


def _landed_tail_start_idx(
    naif_id: int,
    sample_ets: np.ndarray,
    altitude_threshold_km: float,
) -> int | None:
    """Index of the first sample of the longest landed-tail.

    A sample is "landed" if the probe is within `altitude_threshold_km`
    of any major-body surface. The tail is the longest run of consecutive
    landed samples that INCLUDES the last sample. Returns the start index
    of that tail, or None if the probe isn't landed at the end of coverage.

    Why: Phoenix-class landed missions ship SPKs that park the spacecraft
    at lander coordinates and extend 90+ years forward. SPICE's last-
    furnshed-wins precedence makes those parked-coords win over the cruise
    kernel near landing time, producing a 250,000 km step in a single
    sample. Polynomial fits of any degree can't span that. Truncate
    coverage at the start of the landed tail so we only render the
    in-flight phase.
    """
    n = len(sample_ets)
    if n < 2:
        return None
    # Per-sample boolean: is the probe within threshold of any landing body?
    landed = np.zeros(n, dtype=bool)
    for k, et in enumerate(sample_ets):
        for body_naif in _LANDING_TARGETS:
            try:
                state, _ = spiceypy.spkezr(
                    str(naif_id),
                    float(et),
                    "ECLIPJ2000",
                    "NONE",
                    str(body_naif),
                )
            except spiceypy.exceptions.SpiceyError:
                continue
            try:
                radii = spiceypy.bodvrd(str(body_naif), "RADII", 3)[1]
            except spiceypy.exceptions.SpiceyError:
                continue
            dist = float(np.linalg.norm(state[:3]))
            r_max = float(max(radii))
            if (dist - r_max) < altitude_threshold_km:
                landed[k] = True
                break
    if not landed[-1]:
        return None
    # Walk back from the last sample while consecutive landed.
    idx = n - 1
    while idx > 0 and landed[idx - 1]:
        idx -= 1
    if idx == 0:
        # Entire coverage looks landed — leave that case to is_landed_probe.
        return None
    return idx


def classify_trace(
    naif_id: int,
    kernel_paths: list[str],
    sample_dt_days: float = 1.0,
    landed_tail_altitude_km: float = 50.0,
) -> list[ZoneInterval]:
    """Sample the probe's trajectory at `sample_dt_days` cadence and return
    the run-length-encoded zone membership timeline.

    A probe is placed in:
      * any planetary zone whose `r_zone_km` it's inside at that time
      * `interplanetary` at times when it's outside every planetary zone

    Voyager-class deep-space probes are always outside planetary zones and
    are naturally captured by the interplanetary RLE intervals across their
    full coverage. Cruise-then-orbiter probes (GRAIL, LADEE, Cassini post-
    SOI) emit interplanetary only for the cruise portion — once captured
    by a planet system they show up in that planet's zone, not heliocentric.

    If the probe ends its coverage parked on a body's surface (Phoenix,
    InSight, MGS post-aerobrake, etc.) we truncate at the start of that
    landed tail. The cruise-to-surface kernel discontinuity that SPICE
    produces from precedence-driven SPK switching can't be polynomial-fit.
    """
    cov = _coverage(naif_id, kernel_paths)
    if cov is None:
        return []
    t0, t1 = cov
    dt_s = sample_dt_days * _S_PER_DAY
    n_samples = max(2, int(np.ceil((t1 - t0) / dt_s)) + 1)
    ets = np.linspace(t0, t1, n_samples)

    # Truncate the trailing landed phase, if any.
    cut = _landed_tail_start_idx(naif_id, ets, landed_tail_altitude_km)
    if cut is not None and cut >= 2:
        cut_et = float(ets[cut])
        days_dropped = (t1 - cut_et) / _S_PER_DAY
        ets = ets[:cut]
        n_samples = len(ets)
        logger.info(
            "classify_trace naif=%d: truncating landed tail at et=%.0f "
            "(%.1f days dropped)",
            naif_id,
            cut_et,
            days_dropped,
        )

    intervals: list[ZoneInterval] = []
    in_any_planetary = np.zeros(n_samples, dtype=bool)

    for zone in PLANETARY_ZONES:
        if zone.r_zone_km is None:
            continue
        in_zone_mask = np.zeros(n_samples, dtype=bool)
        for k, et in enumerate(ets):
            try:
                state, _ = spiceypy.spkezr(
                    str(naif_id),
                    float(et),
                    "ECLIPJ2000",
                    "NONE",
                    str(zone.barycenter_naif_id),
                )
            except spiceypy.exceptions.SpiceyError:
                continue
            dist = float(np.linalg.norm(state[:3]))
            in_zone_mask[k] = dist < zone.r_zone_km
        if not in_zone_mask.any():
            continue
        in_any_planetary |= in_zone_mask
        # Run-length encode the boolean mask back into [start, end] intervals.
        diffs = np.diff(in_zone_mask.astype(int), prepend=0, append=0)
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        for s, e in zip(starts, ends, strict=True):
            intervals.append(
                ZoneInterval(zone.key, float(ets[s]), float(ets[min(e, n_samples - 1)]))
            )

    # Emit interplanetary intervals only for the run-length-encoded windows
    # where the probe is genuinely outside every planetary zone — never
    # extend to full coverage. Probes that spend their full life outside
    # planet zones (Voyagers, Pioneers, NH, cruisers) are fully covered
    # naturally; hybrid cruise-then-orbiter probes get only their cruise
    # portion in interplanetary, not their orbiter phase.
    out_mask = ~in_any_planetary
    if out_mask.any():
        diffs = np.diff(out_mask.astype(int), prepend=0, append=0)
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        for s, e in zip(starts, ends, strict=True):
            intervals.append(
                ZoneInterval(
                    INTERPLANETARY.key, float(ets[s]), float(ets[min(e, n_samples - 1)])
                )
            )

    return intervals
