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
from typing import NotRequired, TypedDict

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
from space_map_data.probes.attachments import resolve_attachments
from space_map_data.probes.landing_events import load_phases as load_landing_phases
from space_map_data.probes.probe_id import index_by_source, load_registry
from space_map_data.probes.zones import ALL_ZONES, SMALL_BODIES

logger = logging.getLogger(__name__)


# Contributions are chunk-sliced, so one continuous arc arrives as a run of
# spans that meet at chunk boundaries. Anything under a day apart is that
# seam, or a sub-day hole no date-precision event could land in.
_COVERAGE_MERGE_DAYS = 1.0


class CarriedFrom(TypedDict):
    """Where a passenger borrows its position, and for how long."""

    object_id: str
    start_jd: float
    end_jd: float


class ProbeCoverage(TypedDict):
    """One probe's resolvable span. `windows` are the spans a date can be
    turned into a position in; `position_from` is set only on a craft that
    rides another one."""

    start_jd: float
    end_jd: float
    windows: list[tuple[float, float]]
    position_from: NotRequired[CarriedFrom]


# Keyed by `Object.id`.
type ProbeCoverageMap = dict[str, ProbeCoverage]


def _merge_spans(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sorted spans with touching and near-touching neighbours coalesced."""
    merged: list[list[float]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1] + _COVERAGE_MERGE_DAYS:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _compute_probe_coverage(
    plans: list[ProbePlan],
    metas_by_probe_id: dict[int, ProbeMeta],
) -> ProbeCoverageMap:
    """Per-probe coverage across every (zone, chunk_idx) — union of every
    `ChunkContribution`'s span, covering flying and landed contributions
    across zones. Keyed by `Object.id` so a focused probe's coverage is one
    lookup away.

    `windows` are the spans a date can be resolved to a position in, to
    whole-day resolution. An archive with holes in it yields several:
    Pioneer Venus Orbiter is tracked for four years, missing for five, then
    tracked again, and a date in the middle has no spacecraft to draw.
    `start_jd`/`end_jd` bound them all, which is what a reader that predates
    `windows` sees.
    """
    spans_by_probe: dict[int, list[tuple[float, float]]] = {}
    for plan in plans:
        for c in plan.contributions:
            spans_by_probe.setdefault(plan.probe_id, []).append(
                (et_to_jd(c.c_start_et), et_to_jd(c.c_end_et))
            )
    coverage: ProbeCoverageMap = {}
    n_gapped = 0
    for probe_id, spans in spans_by_probe.items():
        meta = metas_by_probe_id.get(probe_id)
        if meta is None:
            logger.warning(
                "probe_coverage: probe_id=%d has contributions but no ProbeMeta; "
                "dropping from coverage manifest",
                probe_id,
            )
            continue
        windows = _merge_spans(spans)
        n_gapped += len(windows) > 1
        coverage[meta.obj_id] = {
            "start_jd": windows[0][0],
            "end_jd": windows[-1][1],
            "windows": windows,
        }
    logger.info(
        "probe_coverage: %d probes, %d with more than one window",
        len(coverage),
        n_gapped,
    )
    return coverage


def _clip(
    windows: list[tuple[float, float]], start: float, end: float
) -> list[tuple[float, float]]:
    out = [(max(s, start), min(e, end)) for s, e in windows]
    return [(s, e) for s, e in out if e > s]


def _subtract(
    windows: list[tuple[float, float]], holes: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    out = list(windows)
    for h_start, h_end in holes:
        cut: list[tuple[float, float]] = []
        for s, e in out:
            if h_start > s:
                cut.append((s, min(e, h_start)))
            if h_end < e:
                cut.append((max(s, h_end), e))
        out = [(s, e) for s, e in cut if e > s]
    return out


def _add_carried_coverage(
    coverage: ProbeCoverageMap,
) -> None:
    """Give each carried craft its carrier's coverage over the ride.

    The passenger has no fits of its own to pack, so nothing renders it and
    the timeline has no window to scrub. Stamping the carrier's windows plus
    a `position_from` pointer lets the frontend read the carrier's position
    under the passenger's identity. A carrier that adds nothing the craft
    already has is not stamped at all — the frontend prefers a craft's own
    record wherever one exists.

    The window runs to the separation instant and no further. Fits are cut to
    whole sub-chunk slots, so a craft's own arc often starts hours after it
    lets go; bridging that here would be guesswork, because `windows` are
    whole chunks and cannot see where the slots actually fall. The frontend
    reads the grid it renders from and carries the craft across.
    """
    n_added = 0
    for attachment in resolve_attachments():
        obj_id = f"probe-{attachment.probe_id}"
        carrier_id = f"probe-{attachment.carrier_probe_id}"
        carrier = coverage.get(carrier_id)
        if carrier is None:
            logger.warning(
                "attachments: %s carries %s but has no coverage; skipped",
                carrier_id,
                obj_id,
            )
            continue
        own = coverage.get(obj_id)
        own_windows = own["windows"] if own else []
        # The union is what gets stamped; the difference only says whether the
        # carrier reaches anywhere this craft cannot already reach itself.
        borrowed = _clip(carrier["windows"], attachment.start_jd, attachment.end_jd)
        if not _subtract(borrowed, own_windows):
            continue
        windows = _merge_spans(own_windows + borrowed)
        coverage[obj_id] = {
            "start_jd": windows[0][0],
            "end_jd": windows[-1][1],
            "windows": windows,
            "position_from": {
                "object_id": carrier_id,
                "start_jd": attachment.start_jd,
                "end_jd": attachment.end_jd,
            },
        }
        n_added += 1
    logger.info("attachments: stamped position_from on %d carried craft", n_added)


def write_probes(
    session: Session,
    download_dir: Path,
    out_dir: Path,
    has_localized: dict[str, bool],
) -> tuple[dict[str, dict], ProbeCoverageMap]:
    """Build per-zone, per-chunk binary files for every probe on disk.

    Incremental export with per-probe fit caching: (1) classify each probe
    to know which (zone, chunk) pairs it touches, (2) pick the stale
    per-(probe, zone, chunk) signatures, (3) re-fit only those and cache the
    result, (4) recompute chunk signatures from per-probe fit hashes and
    pack + atomic-write just the dirty chunks.

    Returns `(zone_manifest, probe_coverage)`. `probe_coverage` is
    `{Object.id: {start_jd, end_jd, windows}}`, stamped onto each probe's
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
    _add_carried_coverage(coverage)
    return zone_manifest, coverage
