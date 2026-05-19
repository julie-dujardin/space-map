"""Walk a probe's SPK coverage and emit which zone(s) it's in over time.

Coarse cadence — we don't need second-by-second resolution. Sampling at
day-scale catches zone transitions to within a day, which is below every
zone's chunk size. A probe is in `interplanetary` always *and* in any
planetary zone it falls inside (dupe is intentional, see `zones.py`).

Per-sample landed detection splits coverage into alternating flying and
landed phases (a probe can land, fly again, and land again — Apollo
splashdowns, GRAIL pre-launch on the pad → lunar impact, sample-return
capsules). Zone classification runs on flying phases only; landed phases
carry just (body, start_et, end_et) for the consumer to decide what to
do with.
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


@dataclass(frozen=True)
class LandedPhase:
    """A contiguous window where the probe sits on a body's surface.

    TODO(landed-export): emit per-phase lat/lng samples in IAU_<BODY> frame
    so the frontend can pin landers on the surface. Detection is in place
    and `scripts/probe_landed_test.py` validates the body-fixed sampling +
    100m / 1-day decimation against published lander coordinates for all
    9 SPK-covered landers (Huygens, InSight, MARS2020, MER×2, MSL,
    Phoenix, Viking×2); the export-side writer doesn't ship anything for
    these yet.

    TODO(landed-events): merge in landers that have no usable SPK at all
    (Mars Pathfinder, Sojourner, most Luna/Venera, Chang'e/Yutu, Zhurong,
    Tianwen-1 lander, Beagle 2, Schiaparelli, Hope, Mangalyaan, MPL, DS2,
    Fobos-Grunt, etc.) by reading `landing_site` blocks from
    research/probe-events/*.json and emitting them as static phases.
    """

    body_naif_id: int
    start_et: float
    end_et: float


@dataclass(frozen=True)
class TraceResult:
    zone_intervals: list[ZoneInterval]
    landed_phases: list[LandedPhase]


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

# IAU body-fixed frame names — used to compute body-fixed velocity for the
# landed-vs-orbiting test. A lander tracks the body's rotation exactly, so
# its body-fixed |v| ≈ 0; a low-altitude orbiter dipping past 50 km still
# moves at ~1.6 km/s in the body-fixed frame.
_IAU_FRAME: dict[int, str] = {
    199: "IAU_MERCURY",
    299: "IAU_VENUS",
    301: "IAU_MOON",
    399: "IAU_EARTH",
    499: "IAU_MARS",
    606: "IAU_TITAN",
}

# Per-sample landed-detection thresholds. Altitude alone false-positives on
# GRAIL/LADEE/MESSENGER perilunes/periherms (~30 km altitude at orbital speed);
# adding the v_bf gate cleanly separates real landers (≤ 8 m/s body-fixed)
# from low orbiters (≥ 1.6 km/s body-fixed). Values held in module scope so
# callers don't have to plumb them through three layers of helpers.
_LANDED_ALT_KM = 50.0
_LANDED_VBF_M_PER_S = 10.0


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


def _positions_wrt_ssb(naif_id: int, ets: np.ndarray) -> np.ndarray:
    """Per-ET position of `naif_id` wrt SSB (ECLIPJ2000, no light-time).

    Returns a `(len(ets), 3)` array; rows where the lookup failed are NaN.
    Single helper so probe / planet / body positions all flow through one
    spkpos call per ET, letting the caller cache and reuse them.
    """
    out = np.full((len(ets), 3), np.nan)
    for k, et in enumerate(ets):
        try:
            pos, _ = spiceypy.spkpos(str(naif_id), float(et), "ECLIPJ2000", "NONE", "0")
            out[k] = pos
        except spiceypy.exceptions.SpiceyError:
            pass
    return out


def _per_sample_landed_body(
    naif_id: int,
    sample_ets: np.ndarray,
    probe_ssb: np.ndarray,
    target_ssb_cache: dict[int, np.ndarray] | None = None,
) -> np.ndarray:
    """Per-sample body NAIF the probe is landed on (or 0 = flying).

    Two-pass test per sample:

      1. Cheap altitude prefilter using cached SSB-relative positions —
         spkpos against each `_LANDING_TARGETS` only touches DE/sat
         kernels (a handful of segments, not the mission's hundreds).
         Samples that aren't within `_LANDED_ALT_KM` of any body skip
         the second pass entirely.

      2. For each candidate sample, spkezr in the body's IAU frame to
         get body-fixed velocity. A lander tracks rotation → |v_bf| ≈ 0;
         a low orbiter at low altitude still has ~1.6 km/s body-fixed.
         Sample is landed iff |v_bf| < `_LANDED_VBF_M_PER_S`.

    `target_ssb_cache` is shared with zone classification (planet bodies
    are not zone barycenters, but the function will mutate the cache so
    later callers can reuse computed SSB tracks).
    """
    n = len(sample_ets)
    near_body = np.zeros(n, dtype=int)
    cache = target_ssb_cache if target_ssb_cache is not None else {}
    for body_naif in _LANDING_TARGETS:
        try:
            radii = spiceypy.bodvrd(str(body_naif), "RADII", 3)[1]
        except spiceypy.exceptions.SpiceyError:
            continue
        r_max = float(max(radii))
        if body_naif not in cache:
            cache[body_naif] = _positions_wrt_ssb(body_naif, sample_ets)
        body_ssb = cache[body_naif]
        rel = probe_ssb - body_ssb
        dist = np.linalg.norm(rel, axis=1)
        # First body that wins claims the sample; bodies are checked in
        # _LANDING_TARGETS order. In practice the candidate sets are
        # disjoint — a probe within 50 km of Earth's surface isn't also
        # within 50 km of the Moon's — so the order doesn't matter.
        mask = (~np.isnan(dist)) & ((dist - r_max) < _LANDED_ALT_KM) & (near_body == 0)
        near_body[mask] = body_naif

    out = np.zeros(n, dtype=int)
    for k in range(n):
        body = int(near_body[k])
        if body == 0:
            continue
        frame = _IAU_FRAME.get(body)
        if frame is None:
            continue
        try:
            state, _ = spiceypy.spkezr(
                str(naif_id), float(sample_ets[k]), frame, "NONE", str(body)
            )
        except spiceypy.exceptions.SpiceyError:
            continue
        v_bf_m_per_s = float(np.linalg.norm(state[3:])) * 1000.0
        if v_bf_m_per_s < _LANDED_VBF_M_PER_S:
            out[k] = body
    return out


def classify_trace(
    naif_id: int,
    kernel_paths: list[str],
    sample_dt_days: float = 1.0,
) -> TraceResult:
    """Sample the probe's trajectory at `sample_dt_days` cadence and return
    the run-length-encoded zone-membership timeline plus any landed phases.

    A probe is placed in:
      * any planetary zone whose `r_zone_km` it's inside at that time
      * `interplanetary` across each flying-phase contiguous range

    Interplanetary is NOT carved by planetary windows — during a flyby (or
    a full captured-orbit phase) the probe is emitted into BOTH the planet
    zone and interplanetary, so the frontend renders correctly in whichever
    view the user is in without having to stitch chunks across zones at the
    boundary moment. See `zones.py` for the rationale.

    Probes with gapped SPK archives (NH has a 2007-2014 hole between the
    Jupiter-flyby and Pluto-approach kernels) are sampled per-contiguous-
    interval and the per-interval classifications are concatenated, so the
    gap doesn't show up as fake interplanetary coverage.

    Landed phases (probe sitting on a major body's surface — altitude <
    50 km AND body-fixed |v| < 10 m/s) are excluded from zone classification
    and returned separately. A probe can have arbitrarily many landed
    phases interleaved with flying ones (Apollo splashdowns, GRAIL's
    pre-launch sample at Cape Canaveral, sample-return capsules).
    """
    merged = _merged_intervals(naif_id, kernel_paths)
    if not merged:
        return TraceResult(zone_intervals=[], landed_phases=[])
    zone_intervals: list[ZoneInterval] = []
    landed_phases: list[LandedPhase] = []
    for t0, t1 in merged:
        zs, ls = _classify_contiguous_interval(naif_id, t0, t1, sample_dt_days)
        zone_intervals.extend(zs)
        landed_phases.extend(ls)
    return TraceResult(zone_intervals=zone_intervals, landed_phases=landed_phases)


def _classify_contiguous_interval(
    naif_id: int,
    t0: float,
    t1: float,
    sample_dt_days: float,
) -> tuple[list[ZoneInterval], list[LandedPhase]]:
    """Classify a single gap-free coverage interval. See `classify_trace`
    for semantics — this is the inner loop body factored out so multi-
    interval probes can call it once per interval."""
    dt_s = sample_dt_days * _S_PER_DAY
    n_samples = max(2, int(np.ceil((t1 - t0) / dt_s)) + 1)
    ets = np.linspace(t0, t1, n_samples)

    # Compute probe-rel-SSB once per ET. This is the dominant cost when a
    # mission has many loaded segments (e.g. MEX with 282 BSPs): each spkpos
    # walks the segment list to find the probe. The per-zone loop below then
    # subtracts cached planet-rel-SSB positions — those calls only touch DE /
    # satellite kernels (a handful of segments) so they're an order of
    # magnitude cheaper. Cuts MEX classify_trace from ~62 min to ~7 min.
    probe_ssb = _positions_wrt_ssb(naif_id, ets)

    # Per-sample landed body (or 0 = flying). RLE into phases; flying ranges
    # get zone classification, landed ranges are recorded standalone.
    target_ssb_cache: dict[int, np.ndarray] = {}
    landed_body = _per_sample_landed_body(
        naif_id, ets, probe_ssb, target_ssb_cache=target_ssb_cache
    )

    zone_intervals: list[ZoneInterval] = []
    landed_phases: list[LandedPhase] = []
    i = 0
    while i < n_samples:
        cur = int(landed_body[i])
        j = i
        while j + 1 < n_samples and int(landed_body[j + 1]) == cur:
            j += 1
        if cur != 0:
            landed_phases.append(
                LandedPhase(
                    body_naif_id=cur, start_et=float(ets[i]), end_et=float(ets[j])
                )
            )
        else:
            _classify_flying_subrange(
                ets, probe_ssb, i, j, target_ssb_cache, zone_intervals
            )
        i = j + 1

    return zone_intervals, landed_phases


def _classify_flying_subrange(
    ets: np.ndarray,
    probe_ssb: np.ndarray,
    s_idx: int,
    e_idx: int,
    target_ssb_cache: dict[int, np.ndarray],
    out: list[ZoneInterval],
) -> None:
    """Run zone classification over `ets[s_idx:e_idx+1]` and append the
    resulting `ZoneInterval`s to `out`.

    Interplanetary spans the full sub-range EXCEPT "captured" periods. A
    zone-X run is captured when the probe is still inside zone X at the
    last sample of this flying sub-range — i.e. it never exits before the
    SPK coverage ends. Captured runs emit ONLY the planet zone; flyby
    runs emit BOTH the planet zone and interplanetary (so the frontend
    can render in either view without a cross-zone handoff at the
    boundary moment, see zones.py).

    Orbiters (MEX in Mars, HST in Earth-Moon, Cassini-post-SOI in Saturn,
    Europa Clipper's future Jupiter orbit, …) have their planet zone as
    the last in-zone run reaching the end of coverage → captured →
    skip interplanetary for that span. A 7-day Kepler/Chebyshev fit
    centered on the Sun can't simultaneously capture the planet's
    heliocentric motion and the spacecraft's much faster planet-centered
    motion; pre-v6 the fit collapsed to "spacecraft ≈ planet" with error
    ≈ planet-Sun distance (~1 AU).
    """
    n_sub = e_idx - s_idx + 1
    if n_sub < 1:
        return
    sub_ets = ets[s_idx : e_idx + 1]
    sub_probe_ssb = probe_ssb[s_idx : e_idx + 1]
    captured_mask = np.zeros(n_sub, dtype=bool)

    for zone in PLANETARY_ZONES:
        if zone.r_zone_km is None:
            continue
        tgt = zone.barycenter_naif_id
        if tgt not in target_ssb_cache:
            target_ssb_cache[tgt] = _positions_wrt_ssb(tgt, ets)
        rel = sub_probe_ssb - target_ssb_cache[tgt][s_idx : e_idx + 1]
        dist = np.linalg.norm(rel, axis=1)
        in_zone_mask = (~np.isnan(dist)) & (dist < zone.r_zone_km)
        if not in_zone_mask.any():
            continue
        diffs = np.diff(in_zone_mask.astype(int), prepend=0, append=0)
        starts = np.where(diffs == 1)[0]
        ends = np.where(diffs == -1)[0]
        for s, e in zip(starts, ends, strict=True):
            out.append(
                ZoneInterval(
                    zone.key,
                    float(sub_ets[s]),
                    float(sub_ets[min(e, n_sub - 1)]),
                )
            )
        # If the probe is still in this zone at the last sample of the
        # flying sub-range, the final in-zone run is "captured" — exclude
        # it from interplanetary.
        if in_zone_mask[-1]:
            captured_mask[starts[-1] :] = True

    # Interplanetary spans the flying sub-range except captured periods.
    interp_mask = ~captured_mask
    if not interp_mask.any():
        return
    diffs = np.diff(interp_mask.astype(int), prepend=0, append=0)
    starts = np.where(diffs == 1)[0]
    ends = np.where(diffs == -1)[0]
    for s, e in zip(starts, ends, strict=True):
        out.append(
            ZoneInterval(
                INTERPLANETARY.key,
                float(sub_ets[s]),
                float(sub_ets[min(e, n_sub - 1)]),
            )
        )
