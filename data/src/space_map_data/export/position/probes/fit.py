"""Pass 2 of the probes exporter: signature check + per-probe re-fit.

`decide_dirty` diffs planned chunks against on-disk sidecars; `fit_pass`
re-furnshes each probe that touches a dirty chunk and runs the expensive
`size_chunk` / `fit_landed_chunk` work only for those (probe, chunk) pairs.
"""

import logging
from collections import defaultdict
from pathlib import Path

import spiceypy

from space_map_data.export.position.probes import sidecar
from space_map_data.export.position.probes.landed import fit_landed_chunk
from space_map_data.export.position.probes.plan import (
    ChunkProbeRecord,
    ProbeMeta,
    ProbePlan,
)
from space_map_data.export.position.probes.sizing import size_chunk
from space_map_data.export.position.probes.time_grid import S_PER_DAY, jd_to_et
from space_map_data.export.position.format import (
    MISSING_ID_TYPE,
    MISSING_INT32,
)
from space_map_data.probes.fit_centers import (
    FitCenterCandidate,
    detect_fit_center,
    fit_center_header_fields,
)
from space_map_data.probes.zones import ZONES_BY_KEY

logger = logging.getLogger(__name__)


def decide_dirty(
    chunk_index: dict[str, dict[int, list[ProbePlan]]],
    metas_by_probe_id: dict[int, ProbeMeta],
    out_dir: Path,
    download_dir: Path,
    candidates_hash_by_zone: dict[str, str],
) -> dict[str, dict[int, dict]]:
    """For each planned chunk, compute its expected signature and compare
    against the on-disk sidecar. Returns `dirty[zone][chunk_idx] = signature`
    for chunks that need re-fitting."""
    probes_dir = out_dir / "position" / "probes"
    dirty: dict[str, dict[int, dict]] = defaultdict(dict)
    for zone_key, chunks in chunk_index.items():
        zone_obj = ZONES_BY_KEY[zone_key]
        zone_out = probes_dir / zone_key
        cand_hash = candidates_hash_by_zone.get(zone_key, "")
        for chunk_idx, plan_list in chunks.items():
            probes_for_sig = [
                (
                    p.probe_id,
                    p.kernels,
                    metas_by_probe_id[p.probe_id].object_type_ordinal,
                    metas_by_probe_id[p.probe_id].has_localized,
                )
                for p in plan_list
            ]
            new_sig = sidecar.build_chunk_signature(
                zone_obj, probes_for_sig, download_dir, cand_hash
            )
            binary_path = zone_out / f"{chunk_idx}.bin.gz"
            sidecar_path = sidecar.mirror_path(zone_out / f"{chunk_idx}.meta.json")
            if binary_path.exists() and sidecar.matches(sidecar_path, new_sig):
                continue
            dirty[zone_key][chunk_idx] = new_sig
    return dirty


def fit_pass(
    plans: list[ProbePlan],
    dirty: dict[str, dict[int, dict]],
    generic_spk_paths: list[Path],
    start_jd: float,
    candidates_by_zone: dict[str, list[FitCenterCandidate]],
) -> dict[str, dict[int, list[ChunkProbeRecord]]]:
    """Pass 2: re-furnish each probe that touches a dirty chunk, fit its
    flying + landed contributions, return `by_zone_chunk[zone][chunk_idx]`.

    Fit-center detection runs per (probe, chunk) while the probe's kernels
    are furnshed. The first flying contribution to a chunk pins the center;
    later contributions to the same chunk reuse it so one probe header
    encodes one center.
    """
    by_zone_chunk: dict[str, dict[int, list[ChunkProbeRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )

    probes_with_dirty: list[ProbePlan] = [
        p
        for p in plans
        if any(c.chunk_idx in dirty.get(c.zone_key, {}) for c in p.contributions)
    ]
    n_dirty_total = sum(len(v) for v in dirty.values())
    logger.info(
        "Probes export: %d dirty chunks to re-fit across %d probes",
        n_dirty_total,
        len(probes_with_dirty),
    )

    for i, plan in enumerate(probes_with_dirty, 1):
        for k in plan.kernels:
            spiceypy.furnsh(str(k))
        for p in generic_spk_paths:
            spiceypy.furnsh(str(p))
        try:
            # Group this probe's dirty contributions by (zone, chunk) so we
            # build at most one ChunkProbeRecord per chunk even when both
            # flying and landed contributions land in the same chunk.
            by_chunk: dict[tuple[str, int], ChunkProbeRecord] = {}
            fit_center_naif_by_key: dict[tuple[str, int], int] = {}
            for c in plan.contributions:
                if c.chunk_idx not in dirty.get(c.zone_key, {}):
                    continue
                zone = ZONES_BY_KEY[c.zone_key]
                chunk_start_et = (
                    jd_to_et(start_jd)
                    + c.chunk_idx * zone.chunk_years * 365.25 * S_PER_DAY
                )
                key = (c.zone_key, c.chunk_idx)
                rec = by_chunk.get(key)
                if c.kind == "flying":
                    sub_s = zone.kepler_subchunk_days * S_PER_DAY
                    cached_center = fit_center_naif_by_key.get(key)
                    if cached_center is None:
                        chosen = detect_fit_center(
                            candidates_by_zone.get(c.zone_key, []),
                            plan.naif_id,
                            c.c_start_et,
                            c.c_end_et,
                        )
                        center_naif = (
                            chosen.naif_id
                            if chosen is not None
                            else zone.fit_center_naif_id
                        )
                        center_id_value, center_id_type = fit_center_header_fields(
                            chosen
                        )
                        fit_center_naif_by_key[key] = center_naif
                    else:
                        center_naif = cached_center
                        center_id_value = (
                            rec.fit_center_id_value if rec else MISSING_INT32
                        )
                        center_id_type = (
                            rec.fit_center_id_type if rec else MISSING_ID_TYPE
                        )
                    chunk_sizing = size_chunk(
                        plan.naif_id,
                        zone,
                        c.c_start_et,
                        c.c_end_et,
                        fit_center_naif_id=center_naif,
                    )
                    if not chunk_sizing.sub_chunks:
                        continue
                    first_offset = int(
                        round(
                            (chunk_sizing.sub_chunks[0].t_start_et - chunk_start_et)
                            / sub_s
                        )
                    )
                    if rec is None:
                        rec = ChunkProbeRecord(
                            probe_id=plan.probe_id,
                            first_offset=first_offset,
                            fit_center_id_value=center_id_value,
                            fit_center_id_type=center_id_type,
                        )
                        by_chunk[key] = rec
                    rec.flying.extend(chunk_sizing.sub_chunks)
                elif c.kind == "landed":
                    assert c.landed_body_naif_id is not None
                    landed_fit = fit_landed_chunk(
                        probe_naif_id=plan.naif_id,
                        body_naif_id=c.landed_body_naif_id,
                        chunk_start_et=chunk_start_et,
                        c_start_et=c.c_start_et,
                        c_end_et=c.c_end_et,
                    )
                    if landed_fit is None:
                        continue
                    if rec is None:
                        rec = ChunkProbeRecord(probe_id=plan.probe_id, first_offset=0)
                        by_chunk[key] = rec
                    rec.landed = landed_fit
            for (zone_key, chunk_idx), rec in by_chunk.items():
                by_zone_chunk[zone_key][chunk_idx].append(rec)
            logger.info(
                "[%d/%d] fit probe_id=%d naif=%d → %d dirty (zone, chunk) entries",
                i,
                len(probes_with_dirty),
                plan.probe_id,
                plan.naif_id,
                len(by_chunk),
            )
        finally:
            for p in generic_spk_paths:
                spiceypy.unload(str(p))
            for k in plan.kernels:
                spiceypy.unload(str(k))

    return by_zone_chunk
