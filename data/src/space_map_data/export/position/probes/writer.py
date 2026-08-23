"""Export probe trajectories as zone-keyed chunk files.

Classifies each spacecraft's coverage into zone intervals, builds Method-C
Kepler or Chebyshev fits per sub-chunk via `probes.sizing.size_chunk`, and
emits one gzipped binary per (zone, chunk_idx) aggregating EVERY probe whose
trajectory intersects it. The frontend loads one zone's chunks at a time,
dispatching per sub-chunk on the method byte.

Chunks align to a global `start_jd` (1950-01-01), matching the chebyshev
exporter's convention. Incremental: per-probe fits are cached, so a change
to one probe's kernels only invalidates that probe's fits — the chunk
sidecar tracks per-probe fit-signature hashes and repacks only the chunks
whose probe set changed (see `fit_cache.py` / `sidecar.py`).

Pipeline split: kernel discovery in `kernels.py`, dataclasses in `plan.py`,
landed-phase fits in `landed.py`, time math in `time_grid.py`, the passes in
`classify.py` / `fit.py` / `write.py`. This module is the top-level
orchestrator.
"""

import logging
from pathlib import Path

import spiceypy
from sqlalchemy.orm import Session

from space_map_data.download.providers.spice.probes import MISSIONS_DIR
from space_map_data.export.position.probes.classify import classify_pass
from space_map_data.export.position.probes.events_classify import (
    classify_events_phases,
)
from space_map_data.export.position.probes import fit_cache
from space_map_data.export.position.probes.fit import (
    build_fits,
    collect_for_repack,
    decide_dirty_chunks,
    expected_fit_sigs,
    stale_fits,
)
from space_map_data.export.position.probes.kernels import collect_generic_kernels
from space_map_data.export.position.probes.plan import (
    ProbeMeta,
    ProbePlan,
    build_probe_metas,
)
from space_map_data.export.position.probes.time_grid import (
    PROBE_EXPORT_END_YEAR,
    PROBE_EXPORT_START_YEAR,
)
from space_map_data.export.position.probes.write import write_pass
from space_map_data.utils.time import et_to_jd, jd_to_et, year_to_jd
from space_map_data.probes.fit_centers import (
    FitCenterCandidate,
    candidates_for_zone,
    candidates_hash,
    fit_center_recode_map,
    load_candidates,
    small_body_candidates,
)
from space_map_data.probes.landing_events import load_phases as load_landing_phases
from space_map_data.probes.probe_id import index_by_source, load_registry
from space_map_data.probes.zones import ALL_ZONES, SMALL_BODIES

logger = logging.getLogger(__name__)


def _compute_probe_coverage(
    plans: list[ProbePlan],
    metas_by_probe_id: dict[int, ProbeMeta],
) -> dict[str, dict[str, float]]:
    """Per-probe outermost coverage envelope across every (zone, chunk_idx) —
    union of every `ChunkContribution`'s span, covering flying and landed
    contributions across zones. Keyed by `Object.id` so a focused probe's
    coverage end is one lookup away."""
    bounds_by_probe: dict[int, tuple[float, float]] = {}
    for plan in plans:
        for c in plan.contributions:
            cur = bounds_by_probe.get(plan.probe_id)
            if cur is None:
                bounds_by_probe[plan.probe_id] = (c.c_start_et, c.c_end_et)
            else:
                bounds_by_probe[plan.probe_id] = (
                    min(cur[0], c.c_start_et),
                    max(cur[1], c.c_end_et),
                )
    coverage: dict[str, dict[str, float]] = {}
    for probe_id, (s_et, e_et) in bounds_by_probe.items():
        meta = metas_by_probe_id.get(probe_id)
        if meta is None:
            logger.warning(
                "probe_coverage: probe_id=%d has contributions but no ProbeMeta; "
                "dropping from coverage manifest",
                probe_id,
            )
            continue
        coverage[meta.obj_id] = {
            "start_jd": et_to_jd(s_et),
            "end_jd": et_to_jd(e_et),
        }
    return coverage


def write_probes(
    session: Session,
    download_dir: Path,
    out_dir: Path,
    has_localized: dict[str, bool],
) -> tuple[dict[str, dict], dict[str, dict[str, float]]]:
    """Build per-zone, per-chunk binary files for every probe on disk.

    Incremental export with per-probe fit caching: (1) classify each probe
    to know which (zone, chunk) pairs it touches, (2) pick the stale
    per-(probe, zone, chunk) signatures, (3) re-fit only those and cache the
    result, (4) recompute chunk signatures from per-probe fit hashes and
    pack + atomic-write just the dirty chunks.

    Returns `(zone_manifest, probe_coverage)`. `probe_coverage` is
    `{Object.id: {start_jd, end_jd}}`, stamped onto each probe's
    `__global__` entry for the frontend coverage-end pause.
    """
    if not MISSIONS_DIR.exists():
        logger.info("No probe missions at %s, skipping probe export", MISSIONS_DIR)
        return {}, {}

    probe_registry = load_registry()
    probe_source_index = index_by_source(probe_registry)
    metas_by_probe_id = build_probe_metas(session, has_localized)
    start_jd = year_to_jd(PROBE_EXPORT_START_YEAR)
    end_jd = year_to_jd(PROBE_EXPORT_END_YEAR)

    lsk_pck_paths, generic_spk_paths = collect_generic_kernels(
        download_dir / "sources" / "position" / "spice-kernels"
    )
    for p in lsk_pck_paths:
        spiceypy.furnsh(str(p))
    logger.info(
        "Probes export: furnished %d LSK/PCK kernels (outer scope); "
        "%d generic SPKs will be (un)furnshed per-probe after mission "
        "kernels so they win for shared targets",
        len(lsk_pck_paths),
        len(generic_spk_paths),
    )

    chebyshev_cache_dir = download_dir / "derived" / "position" / "chebyshev"
    all_candidates = load_candidates(chebyshev_cache_dir)
    candidates_by_zone: dict[str, list[FitCenterCandidate]] = {}
    candidates_hash_by_zone: dict[str, str] = {}
    for zone in ALL_ZONES:
        if zone.key == SMALL_BODIES.key:
            # Curated target list, not the npz-derived set — see
            # `small_body_candidates` on why these stay out of interplanetary.
            zone_cands = small_body_candidates()
        else:
            zone_cands = candidates_for_zone(all_candidates, zone)
        candidates_by_zone[zone.key] = zone_cands
        candidates_hash_by_zone[zone.key] = candidates_hash(zone_cands)
    logger.info(
        "Probes export: %d candidate fit centers loaded (%s)",
        len(all_candidates),
        ", ".join(f"{k}={len(v)}" for k, v in candidates_by_zone.items() if v)
        or "no overrides",
    )

    try:
        plans, chunk_index = classify_pass(
            probe_registry,
            probe_source_index,
            metas_by_probe_id,
            lsk_pck_paths,
            generic_spk_paths,
            start_jd,
        )

        # Events-driven landings for probes without SPK coverage (Apollo
        # descent stages, Veneras, Pathfinder, Beagle 2, …). Synthesised
        # plans have empty kernels; the fit pass detects that and builds
        # a static LandedFit directly from the events JSON's lat/lng.
        events_phases = load_landing_phases(jd_to_et(end_jd))
        events_plans, events_chunk_index = classify_events_phases(
            events_phases,
            probe_registry,
            metas_by_probe_id,
            start_jd,
        )
        plans.extend(events_plans)
        for zone_key, by_chunk in events_chunk_index.items():
            for chunk_idx, plan_list in by_chunk.items():
                chunk_index[zone_key][chunk_idx].extend(plan_list)

        sigs = expected_fit_sigs(plans, download_dir, candidates_hash_by_zone)
        stale = stale_fits(sigs)
        canonical_naif_by_probe_id = {
            int(e["probe_id"]): int(e["naif_id"]) for e in probe_registry
        }
        build_fits(
            plans,
            stale,
            generic_spk_paths,
            start_jd,
            candidates_by_zone,
            canonical_naif_by_probe_id,
        )
        fit_cache.prune_orphans(set(sigs.keys()))
        dirty = decide_dirty_chunks(chunk_index, sigs, metas_by_probe_id, out_dir)
        by_zone_chunk = collect_for_repack(dirty, chunk_index)
    finally:
        spiceypy.kclear()

    fit_center_recode = fit_center_recode_map(
        [c for zone_cands in candidates_by_zone.values() for c in zone_cands]
    )
    zone_manifest = write_pass(
        chunk_index,
        dirty,
        by_zone_chunk,
        metas_by_probe_id,
        out_dir,
        start_jd,
        end_jd,
        fit_center_recode,
    )
    coverage = _compute_probe_coverage(plans, metas_by_probe_id)
    return zone_manifest, coverage
