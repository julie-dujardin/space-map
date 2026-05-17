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

    Probes with gapped coverage (e.g. NH's Sep-2007 → Dec-2014 hole between
    Jupiter-flyby and Pluto-approach kernels) are sampled per-interval —
    samples in the gap would produce SPICE errors, and a probe that's in
    flight in any interval is by definition not landed.
    """
    intervals = _merged_intervals(naif_id, kernel_paths)
    if not intervals:
        return False, None
    n_per_interval = 5
    sample_ets: list[float] = []
    for t0, t1 in intervals:
        if t1 - t0 < 120:  # interval too short to leave 60 s margins on both ends
            continue
        sample_ets.extend(np.linspace(t0 + 60, t1 - 60, n_per_interval))
    if not sample_ets:
        return False, None

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
    if best_n == len(sample_ets):
        return True, best_body
    return False, None


def _merged_intervals(
    naif_id: int, kernel_paths: list[str]
) -> list[tuple[float, float]]:
    """All contiguous SPK coverage intervals for `naif_id`, merged across
    overlapping/touching kernels and sorted by start.

    Returns an empty list when no kernel covers `naif_id`. Multiple intervals
    indicate gaps in the timeline — NH's archive has a 7-year hole between
    its 2006-2007 cruise kernel and its 2014-onwards Pluto-approach kernels,
    and the writer needs to see both so the pre-gap trajectory shows up too.
    """
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
        return []
    intervals.sort()
    merged: list[list[float]] = [list(intervals[0])]
    for s, e in intervals[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(iv[0], iv[1]) for iv in merged]


def inception_et(naif_id: int, kernel_paths: list[str]) -> float | None:
    """Start of the longest contiguous coverage interval — the canonical
    "this probe came into being" timestamp for `probe_id` assignment.

    Picking the *longest* (not earliest) interval keeps `probe_id`s stable
    when an archive grows a short pre-mission test interval that didn't
    exist at first ingest. The cache in `probe_id.py` already pins each
    `(mission, naif_id)` once assigned, so this only matters for probes
    ingested for the first time.
    """
    intervals = _merged_intervals(naif_id, kernel_paths)
    if not intervals:
        return None
    return max(intervals, key=lambda iv: iv[1] - iv[0])[0]


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
      * `interplanetary` across the full contiguous coverage interval

    Interplanetary is NOT carved by planetary windows — during a flyby (or
    a full captured-orbit phase) the probe is emitted into BOTH the planet
    zone and interplanetary, so the frontend renders correctly in whichever
    view the user is in without having to stitch chunks across zones at the
    boundary moment. See `zones.py` for the rationale.

    Probes with gapped SPK archives (NH has a 2007-2014 hole between the
    Jupiter-flyby and Pluto-approach kernels) are sampled per-contiguous-
    interval and the per-interval classifications are concatenated, so the
    gap doesn't show up as fake interplanetary coverage.

    If a contiguous interval ends with the probe parked on a body's surface
    (Phoenix, InSight, MGS post-aerobrake, …) we truncate at the start of
    that landed tail. The cruise-to-surface kernel discontinuity that SPICE
    produces from precedence-driven SPK switching can't be polynomial-fit.
    """
    merged = _merged_intervals(naif_id, kernel_paths)
    if not merged:
        return []
    out: list[ZoneInterval] = []
    for t0, t1 in merged:
        out.extend(
            _classify_contiguous_interval(
                naif_id, t0, t1, sample_dt_days, landed_tail_altitude_km
            )
        )
    return out


def _classify_contiguous_interval(
    naif_id: int,
    t0: float,
    t1: float,
    sample_dt_days: float,
    landed_tail_altitude_km: float,
) -> list[ZoneInterval]:
    """Classify a single gap-free coverage interval. See `classify_trace`
    for the per-zone / per-interval semantics — this is the inner loop body
    factored out so multi-interval probes can call it once per interval."""
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
        # Run-length encode the boolean mask back into [start, end] intervals.
        diffs = np.diff(in_zone_mask.astype(int), prepend=0, append=0)
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        for s, e in zip(starts, ends, strict=True):
            intervals.append(
                ZoneInterval(zone.key, float(ets[s]), float(ets[min(e, n_samples - 1)]))
            )

    # Interplanetary spans the full contiguous coverage interval — flybys
    # are NOT carved out. The probe co-exists in interplanetary and the
    # planet zone during a flyby so the frontend can render it in whichever
    # view the user is looking at without cross-zone handoff at the
    # boundary moment (see zones.py docstring).
    intervals.append(ZoneInterval(INTERPLANETARY.key, float(ets[0]), float(ets[-1])))

    return intervals
