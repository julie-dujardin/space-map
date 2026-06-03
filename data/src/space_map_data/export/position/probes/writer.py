"""Export probe trajectories as zone-keyed chunk files.

Walks `space-map-downloads/spice/kernels/missions/*/_index.json`, classifies
each spacecraft's coverage into zone intervals, builds Method-C Kepler or
Chebyshev fits per sub-chunk via `probes.sizing.size_chunk`, and emits one
gzipped binary per (zone, chunk_idx) under `position/probes/{zone}/{chunk}.bin.gz`.

One file aggregates EVERY probe whose trajectory intersects that (zone,
chunk_idx). The frontend loads one zone's chunks at a time (driven by the
camera focus), and within a chunk dispatches per sub-chunk on the method
byte to evaluate position(t).

Time-axis alignment: chunks align to a global `start_jd` (1950-01-01) so the
chunk index for a given JD is `floor((jd - start_jd) / chunk_days)`, matching
the chebyshev exporter's convention.

Incremental: each chunk emits a JSON sidecar with `(fit_version, zone_hash,
probes→kernel mtime+size)`. On re-export we recompute that signature and
skip the chunk if it matches what's on disk. See `sidecar.py`.

Pipeline split: kernel discovery in `kernels.py`, dataclasses in `plan.py`,
landed-phase fits in `landed.py`, time math in `time_grid.py`, the three
passes in `classify.py` / `fit.py` / `write.py`. This module is the
top-level orchestrator.
"""

import logging
from pathlib import Path

import spiceypy
from sqlalchemy.orm import Session

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.spice.probes import MISSIONS_DIR
from space_map_data.export.position.probes.classify import classify_pass
from space_map_data.export.position.probes.fit import decide_dirty, fit_pass
from space_map_data.export.position.probes.kernels import collect_generic_kernels
from space_map_data.export.position.probes.plan import build_probe_metas
from space_map_data.export.position.probes.time_grid import (
    PROBE_EXPORT_END_YEAR,
    PROBE_EXPORT_START_YEAR,
)
from space_map_data.export.position.probes.write import write_pass
from space_map_data.utils.time import year_to_jd
from space_map_data.probes.fit_centers import (
    FitCenterCandidate,
    candidates_for_zone,
    candidates_hash,
    load_candidates,
)
from space_map_data.probes.probe_id import index_by_source, load_registry
from space_map_data.probes.zones import ALL_ZONES

logger = logging.getLogger(__name__)


def write_probes(
    session: Session,
    download_dir: Path,
    out_dir: Path,
    has_localized: dict[str, bool],
) -> dict[str, dict]:
    """Build per-zone, per-chunk binary files for every probe on disk.

    Three-pass incremental export:
      1. Classify each probe (furnish + spkezr) to know which chunks it
         touches. No fitting yet.
      2. Compare planned-chunk signatures against on-disk sidecars; only
         "dirty" chunks proceed.
      3. Re-furnish each probe that touches a dirty chunk and run the
         expensive `size_chunk` fits only on those (probe, chunk) pairs.
      4. Pack + atomic-write binary + sidecar per dirty chunk.

    Returns `{zone_key_with_prefix: {chunks, chunk_days, start_jd, end_jd}}`
    so `_build_position_metadata` can fold it into the manifest.
    """
    if not MISSIONS_DIR.exists():
        logger.info("No probe missions at %s, skipping probe export", MISSIONS_DIR)
        return {}

    probe_registry = load_registry()
    probe_source_index = index_by_source(probe_registry)
    metas_by_probe_id = build_probe_metas(session, has_localized)
    start_jd = year_to_jd(PROBE_EXPORT_START_YEAR)
    end_jd = year_to_jd(PROBE_EXPORT_END_YEAR)

    lsk_pck_paths, generic_spk_paths = collect_generic_kernels(
        download_dir / PROVIDERS.SPICE / "kernels"
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

    chebyshev_cache_dir = download_dir / PROVIDERS.SPICE / "chebyshev"
    all_candidates = load_candidates(chebyshev_cache_dir)
    candidates_by_zone: dict[str, list[FitCenterCandidate]] = {}
    candidates_hash_by_zone: dict[str, str] = {}
    for zone in ALL_ZONES:
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
        dirty = decide_dirty(
            chunk_index,
            metas_by_probe_id,
            out_dir,
            download_dir,
            candidates_hash_by_zone,
        )
        by_zone_chunk = fit_pass(
            plans, dirty, generic_spk_paths, start_jd, candidates_by_zone
        )
    finally:
        spiceypy.kclear()

    return write_pass(
        chunk_index,
        dirty,
        by_zone_chunk,
        metas_by_probe_id,
        out_dir,
        start_jd,
        end_jd,
    )
