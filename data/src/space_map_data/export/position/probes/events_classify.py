"""Classify events-driven landed phases into ProbePlans.

The SPICE classify pass (``classify.py``) walks mission kernel trees and
derives landed phases from body-fixed motion. This module covers the
complement: probes whose only registry source is ``EVENTS-DB`` and whose
landings live in ``sources/position/probe-events/*.json``. No SPICE,
no parallelism — pure JSON-to-plans.

Routing:
  * Planet/moon NAIF target → ``zone_for_landed_body`` (mars/earth-moon/
    saturn/…); the planet zone owns the chunk file.
  * Asteroid/comet SPKID target → ``interplanetary`` zone, ``system_naif=0``
    (SSB). The frontend's `renderLandedProbe` parents the probe to the
    body's row at render time using lat/lng + the body's IAU pole.
"""

import logging
from collections import defaultdict

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import ID_TYPE_ORDINAL
from space_map_data.export.position.probes.plan import (
    ChunkContribution,
    ProbeMeta,
    ProbePlan,
    system_naif_for_landed_body,
    zone_for_landed_body,
)
from space_map_data.export.position.probes.time_grid import landed_chunk_range
from space_map_data.probes.landing_events import LandingPhase
from space_map_data.probes.zones import INTERPLANETARY

logger = logging.getLogger(__name__)

_NAIF_ORDINAL = ID_TYPE_ORDINAL[ID_TYPES.NAIF]


def classify_events_phases(
    phases: list[LandingPhase],
    probe_registry: list[dict],
    metas_by_probe_id: dict[int, ProbeMeta],
    start_jd: float,
) -> tuple[list[ProbePlan], dict[str, dict[int, list[ProbePlan]]]]:
    """Build events-only ProbePlans. Returns the same shape as
    ``classify_pass`` so the orchestrator can merge them.

    One ``ProbePlan`` per probe_id (regardless of how many phases that probe
    has). Phases on the same body extend the same plan's contribution list.
    Probes already represented in the plans from ``classify_pass`` (because
    they have SPK coverage too) are NOT touched here — the SPICE pipeline
    owns them.

    `probe_registry` lets us read the canonical NAIF (we don't store it on
    the LandingPhase). `metas_by_probe_id` gates emission: a phase whose
    probe has no Object row is dropped + logged (run the ingest pass first).
    """
    by_pid: dict[int, ProbePlan] = {}
    chunk_index: dict[str, dict[int, list[ProbePlan]]] = defaultdict(
        lambda: defaultdict(list)
    )
    # Registry naif lookup — events-only probes don't furnish kernels, but
    # the plan still records the canonical naif for parity with SPICE plans.
    naif_by_pid = {int(e["probe_id"]): int(e["naif_id"]) for e in probe_registry}

    n_dropped_no_meta = 0
    n_dropped_no_zone = 0
    for ph in phases:
        meta = metas_by_probe_id.get(ph.probe_id)
        if meta is None:
            n_dropped_no_meta += 1
            logger.warning(
                "events_classify: probe %s (probe_id=%d) has no Object row; "
                "skipping. Re-run probes ingest to pick up EVENTS-DB-only probes.",
                ph.probe_name,
                ph.probe_id,
            )
            continue
        zone, sys_naif = _route(ph)
        if zone is None or sys_naif is None:
            n_dropped_no_zone += 1
            continue
        plan = by_pid.get(ph.probe_id)
        if plan is None:
            plan = ProbePlan(
                probe_id=ph.probe_id,
                naif_id=naif_by_pid.get(ph.probe_id, 0),
                kernels=[],
            )
            by_pid[ph.probe_id] = plan
        plan.system_intervals.append((ph.start_et, ph.end_et, sys_naif))
        for chunk_idx, c_start, c_end in landed_chunk_range(
            zone.chunk_days, ph.start_et, ph.end_et, start_jd
        ):
            contrib = ChunkContribution(
                zone_key=zone.key,
                chunk_idx=chunk_idx,
                c_start_et=c_start,
                c_end_et=c_end,
                kind="landed",
                landed_body_id_value=ph.body_id_value,
                landed_body_id_type=ph.body_id_type,
                static_lat_lng=(ph.lat_deg, ph.lng_deg),
            )
            plan.contributions.append(contrib)
            chunk_index[zone.key][chunk_idx].append(plan)

    # Merge system_intervals per plan: a probe with multiple phases on the
    # same body collapses to a single span; back-to-back hops on the same
    # asteroid likewise collapse. ``classify._compute_system_intervals``
    # does the same coalescing for SPICE plans.
    for plan in by_pid.values():
        plan.system_intervals = _merge_intervals(plan.system_intervals)

    logger.info(
        "events_classify: %d phases → %d plans, %d touched chunks "
        "(dropped: %d no Object row, %d no routing)",
        len(phases),
        len(by_pid),
        sum(len(c) for v in chunk_index.values() for c in v.values()),
        n_dropped_no_meta,
        n_dropped_no_zone,
    )
    return list(by_pid.values()), chunk_index


def _route(ph: LandingPhase):
    """Return ``(zone, system_naif)`` for a phase, or ``(None, None)`` to skip.

    Planet/moon NAIF → ``zone_for_landed_body``. Asteroid/comet SPKID →
    interplanetary + SSB barycenter (the asteroid's heliocentric position
    is interpolated by chebyshev; the probe rides on top of it).
    """
    if ph.body_id_type == _NAIF_ORDINAL:
        z = zone_for_landed_body(ph.body_id_value)
        if z is None:
            logger.warning(
                "events_classify: %s landing on NAIF %d has no zone mapping; skipping",
                ph.probe_name,
                ph.body_id_value,
            )
            return None, None
        return z, system_naif_for_landed_body(ph.body_id_value)
    # SPKID: asteroid/comet — render in interplanetary.
    return INTERPLANETARY, 0


def _merge_intervals(
    raw: list[tuple[float, float, int]],
) -> list[tuple[float, float, int]]:
    if not raw:
        return []
    raw = sorted(raw)
    merged: list[list[float | int]] = [list(raw[0])]
    for s, e, sn in raw[1:]:
        last = merged[-1]
        if sn == last[2] and s <= last[1]:
            last[1] = max(last[1], e)
        else:
            merged.append([s, e, sn])
    return [(float(s), float(e), int(sn)) for s, e, sn in merged]
