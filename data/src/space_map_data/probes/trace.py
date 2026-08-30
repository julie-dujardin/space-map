"""Walk a probe's SPK coverage and emit which zone(s) it's in over time.

Day-scale sampling — zone transitions land within a day, well below any
zone's chunk size. A probe is always in `interplanetary` *and* any
planetary zone it falls inside (dupe intentional, see `zones.py`).

Per-sample landed detection splits coverage into alternating flying and
landed phases (a probe can land, fly, and land again — Apollo splashdowns,
GRAIL's pad-to-impact, sample-return capsules). Zone classification runs on
flying phases only; landed phases carry just (body, start_et, end_et).
"""

import logging
from dataclasses import dataclass

import numpy as np
import spiceypy

from space_map_data.probes.small_bodies import (
    SMALL_BODY_TARGET_NAIF_IDS,
    SMALL_BODY_ZONE_RADIUS_KM,
)
from space_map_data.probes.zones import (
    INTERPLANETARY,
    PLANETARY_ZONES,
    SMALL_BODIES,
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
    """A contiguous window where the probe sits on a body's surface,
    derived from body-fixed SPK motion in `classify_trace`. The events-
    driven counterpart (no SPK, lat/lng straight from curated JSON) lives
    in `probes/landing_events.py`."""

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

# The scan runs on a day grid, which puts a touchdown up to a day late: the
# landing date on the page is wrong and the descent that leads to it has no
# record. Each landed edge is bisected down to this, cheap because only the
# two samples either side of a transition are re-tested.
_LANDED_EDGE_TOL_S = 60.0

# A different question from `_LANDED_VBF_M_PER_S`, which asks "lander or low
# orbiter?" — a craft under a parachute already answers that one (Huygens
# clears it 67 min above Titan). Dating the touchdown asks "at rest?", which
# only a craft tracking the body's rotation answers. A phase whose landed
# sample never passes it keeps the scan's own boundary.
_AT_REST_VBF_M_PER_S = 1.0


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
    targets: tuple[int, ...] = _LANDING_TARGETS,
    vbf_max_m_per_s: float = _LANDED_VBF_M_PER_S,
) -> np.ndarray:
    """Per-sample body NAIF the probe is landed on (or 0 = flying).

    Two-pass: (1) cheap altitude prefilter via cached SSB positions — only
    touches DE/sat kernels, not the mission's hundreds of segments; samples
    outside `_LANDED_ALT_KM` of every body skip pass two. (2) body-fixed
    velocity via spkezr in the body's IAU frame — a lander tracks rotation
    (|v_bf| ≈ 0), a low orbiter doesn't (~1.6 km/s); landed iff
    |v_bf| < `_LANDED_VBF_M_PER_S`.

    `target_ssb_cache` is shared with zone classification so later callers
    reuse computed SSB tracks.
    """
    n = len(sample_ets)
    near_body = np.zeros(n, dtype=int)
    cache = target_ssb_cache if target_ssb_cache is not None else {}
    for body_naif in targets:
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
        if v_bf_m_per_s < vbf_max_m_per_s:
            out[k] = body
    return out


def _is_at_rest_at(naif_id: int, et: float, body_naif: int) -> bool:
    """Whether the craft is down on `body_naif` at one instant."""
    ets = np.asarray([et])
    landed = _per_sample_landed_body(
        naif_id,
        ets,
        _positions_wrt_ssb(naif_id, ets),
        targets=(body_naif,),
        vbf_max_m_per_s=_AT_REST_VBF_M_PER_S,
    )
    return int(landed[0]) != 0


def _refine_landed_edge(
    naif_id: int, body_naif: int, flying_et: float, landed_et: float
) -> float:
    """The instant the craft touches down on (or lifts off from) `body_naif`,
    bisected between the last flying sample and the first landed one.

    The endpoints were classified by the phase gate, not the at-rest one, so
    the landed end may not itself read as at rest; then nothing moves and the
    scan's own boundary stands. The result never leaves the bracket either
    way, so it cannot overlap the flying range.
    """
    while abs(landed_et - flying_et) > _LANDED_EDGE_TOL_S:
        mid = 0.5 * (flying_et + landed_et)
        if _is_at_rest_at(naif_id, mid, body_naif):
            landed_et = mid
        else:
            flying_et = mid
    return landed_et


def classify_trace(
    naif_id: int,
    kernel_paths: list[str],
    sample_dt_days: float = 1.0,
) -> TraceResult:
    """Sample the trajectory at `sample_dt_days` cadence; return the RLE
    zone-membership timeline plus any landed phases.

    A probe is placed in any planetary zone it's inside, plus
    `interplanetary` across each flying-phase range — not carved by
    planetary windows, so a flyby or captured orbit lands in BOTH, letting
    the frontend render either view without a cross-zone stitch (see
    `zones.py`).

    Gapped SPK archives (NH's 2007-2014 hole between Jupiter-flyby and
    Pluto-approach kernels) are classified per-contiguous-interval so the
    gap isn't misread as interplanetary coverage.

    Landed phases (altitude < 50 km AND body-fixed |v| < 10 m/s) are
    excluded from zone classification and returned separately; a probe can
    have several, interleaved with flying ones (Apollo splashdowns, GRAIL's
    pad sample, sample-return capsules).
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

    # Compute probe-rel-SSB once per ET — dominant cost for missions with
    # many segments (MEX has 282 BSPs). The per-zone loop below then
    # subtracts cached planet-rel-SSB positions, which only touch a handful
    # of DE/satellite kernel segments. Cuts MEX classify_trace 62min -> 7min.
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
            # Edges only: the scan's samples are a day apart, a landing is an
            # instant.
            start_et = (
                _refine_landed_edge(naif_id, cur, float(ets[i - 1]), float(ets[i]))
                if i > 0 and int(landed_body[i - 1]) == 0
                else float(ets[i])
            )
            end_et = (
                _refine_landed_edge(naif_id, cur, float(ets[j + 1]), float(ets[j]))
                if j + 1 < n_samples and int(landed_body[j + 1]) == 0
                else float(ets[j])
            )
            landed_phases.append(
                LandedPhase(body_naif_id=cur, start_et=start_et, end_et=end_et)
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
    """Run zone classification over `ets[s_idx:e_idx+1]`, appending
    `ZoneInterval`s to `out`.

    Interplanetary spans the sub-range except "captured" periods — a
    zone-X run still inside zone X at the sub-range's last sample (never
    exits before SPK coverage ends). Captured runs emit only the planet
    zone; flyby runs emit both, so the frontend can render either view
    without a cross-zone handoff (see zones.py).

    Orbiters (MEX at Mars, HST at Earth-Moon, Cassini post-SOI, …) end
    their coverage captured, so skip interplanetary for that span: a
    7-day Sun-centered fit can't capture both the planet's heliocentric
    motion and the spacecraft's faster planet-centered motion — folding a
    captured span into interplanetary would blow up to ~1 AU error.
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

    # Small-body encounters: per-target distance membership, dual-listed
    # with interplanetary (a heliocentric fit of a small-body orbiter stays
    # valid — the local orbit is metres-to-km scale, unlike planet orbiters
    # — so no captured-exclusion). Targets without SPK coverage at these
    # epochs yield NaN distances and drop out. The target must also be
    # closer than every planet: Apophis's 2029 pass brings it within the
    # membership radius of the entire Earth-satellite population, and those
    # belong to earth-moon, not to Apophis — while OSIRIS-APEX riding along
    # 100 km from Apophis during that same pass stays in.
    min_planet_dist = np.full(n_sub, np.inf)
    for zone in PLANETARY_ZONES:
        rel = (
            sub_probe_ssb - target_ssb_cache[zone.barycenter_naif_id][s_idx : e_idx + 1]
        )
        dist = np.linalg.norm(rel, axis=1)
        min_planet_dist = np.fmin(
            min_planet_dist, np.where(np.isnan(dist), np.inf, dist)
        )
    small_body_mask = np.zeros(n_sub, dtype=bool)
    for tgt in SMALL_BODY_TARGET_NAIF_IDS:
        if tgt not in target_ssb_cache:
            target_ssb_cache[tgt] = _positions_wrt_ssb(tgt, ets)
        rel = sub_probe_ssb - target_ssb_cache[tgt][s_idx : e_idx + 1]
        dist = np.linalg.norm(rel, axis=1)
        small_body_mask |= (
            (~np.isnan(dist))
            & (dist < SMALL_BODY_ZONE_RADIUS_KM)
            & (dist < min_planet_dist)
        )
    if small_body_mask.any():
        diffs = np.diff(small_body_mask.astype(int), prepend=0, append=0)
        for s, e in zip(np.where(diffs == 1)[0], np.where(diffs == -1)[0], strict=True):
            out.append(
                ZoneInterval(
                    SMALL_BODIES.key,
                    float(sub_ets[s]),
                    float(sub_ets[min(e, n_sub - 1)]),
                )
            )

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
