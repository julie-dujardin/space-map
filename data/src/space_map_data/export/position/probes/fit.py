"""Pass 2 of the probes exporter: per-probe fit cache + chunk dirty check.

Two sub-passes:

  * ``stale_fits`` + ``build_fits`` — per-probe granularity. For each
    (probe, zone, chunk) contribution we compute a per-probe signature
    that captures only THIS probe's inputs (its kernels, plus the zone /
    candidates / events hashes the probe actually depends on). If the
    cache under ``EXPORT_METADATA_DIR/position/probes/_fits/...`` matches,
    the expensive ``size_chunk`` / ``fit_landed_chunk`` work is skipped.
    Otherwise we re-furnish and re-fit, then save the resulting
    ``ChunkProbeRecord`` to cache.

  * ``decide_dirty_chunks`` + ``collect_for_repack`` — chunk granularity.
    The chunk sidecar records each contributing probe's fit-signature
    hash; if the on-disk sidecar matches the recomputed one the binary
    doesn't need rebuilding. Otherwise we load every contributing probe's
    cached fit and hand them to the write pass.

This split decouples "a single probe's inputs changed" from "this chunk's
binary needs rewriting": a kernel edit on Voyager 2 only re-fits Voyager 2,
even when its interplanetary chunks are shared with Voyager 1, Pioneer, etc.
"""

import logging
from collections import defaultdict
from pathlib import Path

import spiceypy

from space_map_data.export.position.probes import fit_cache, sidecar
from space_map_data.export.position.probes.landed import LandedFit, fit_landed_chunk
from space_map_data.export.position.probes.plan import (
    ChunkProbeRecord,
    ProbeMeta,
    ProbePlan,
)
from space_map_data.export.position.probes.sizing import size_chunk
from space_map_data.utils.time import S_PER_DAY, jd_to_et
from space_map_data.export.position.format import (
    MISSING_ID_TYPE,
    MISSING_INT32,
)
from space_map_data.probes.fit_centers import (
    FitCenterCandidate,
    detect_fit_center,
    fit_center_header_fields,
)
from space_map_data.probes.zones import INTERPLANETARY, ZONES_BY_KEY

logger = logging.getLogger(__name__)


def _clip_system_intervals(
    intervals: list[tuple[float, float, int]],
    chunk_start_et: float,
    chunk_end_et: float,
) -> list[tuple[float, float, int]]:
    """Intersect each interval with `[chunk_start_et, chunk_end_et)`, dropping
    any that fall entirely outside."""
    out: list[tuple[float, float, int]] = []
    for s, e, sn in intervals:
        cs = s if s > chunk_start_et else chunk_start_et
        ce = e if e < chunk_end_et else chunk_end_et
        if ce > cs:
            out.append((cs, ce, sn))
    return out


def expected_fit_sigs(
    plans: list[ProbePlan],
    download_dir: Path,
    candidates_hash_by_zone: dict[str, str],
) -> dict[tuple[int, str, int], dict]:
    """Build the expected per-(probe, zone, chunk) signature for every
    contribution in `plans`. Flying / landed presence drives whether
    candidates_hash / events_hash fold in — see `fit_cache.build_fit_signature`.

    When multiple plans share a probe_id (e.g. Cassini classified across
    two mission dirs), the kernel list folded into the signature is the
    union of all plans' kernels — matching the union that `build_fits`
    will actually furnish to produce the merged record.
    """
    events_hash = sidecar.events_files_hash()
    kernels_by_probe: dict[int, list[Path]] = defaultdict(list)
    seen_kernels: dict[int, set[Path]] = defaultdict(set)
    for p in plans:
        for k in p.kernels:
            if k in seen_kernels[p.probe_id]:
                continue
            seen_kernels[p.probe_id].add(k)
            kernels_by_probe[p.probe_id].append(k)
    presence: dict[tuple[int, str, int], dict[str, bool]] = defaultdict(
        lambda: {"flying": False, "landed": False}
    )
    for p in plans:
        for c in p.contributions:
            key = (p.probe_id, c.zone_key, c.chunk_idx)
            if c.kind == "flying":
                presence[key]["flying"] = True
            elif c.kind == "landed":
                presence[key]["landed"] = True

    sigs: dict[tuple[int, str, int], dict] = {}
    for (probe_id, zone_key, chunk_idx), kinds in presence.items():
        zone = ZONES_BY_KEY[zone_key]
        sigs[(probe_id, zone_key, chunk_idx)] = fit_cache.build_fit_signature(
            zone=zone,
            kernels=kernels_by_probe[probe_id],
            download_dir=download_dir,
            candidates_hash=candidates_hash_by_zone.get(zone_key, ""),
            events_hash=events_hash,
            has_flying=kinds["flying"],
            has_landed=kinds["landed"],
        )
    return sigs


def stale_fits(
    expected_sigs: dict[tuple[int, str, int], dict],
) -> dict[tuple[int, str, int], dict]:
    """Subset of `expected_sigs` whose on-disk cache signature doesn't match.
    These are the (probe, zone, chunk) tuples that need re-fitting."""
    return {
        key: sig
        for key, sig in expected_sigs.items()
        if not fit_cache.is_cached(*key, sig)
    }


def build_fits(
    plans: list[ProbePlan],
    stale_sigs: dict[tuple[int, str, int], dict],
    generic_spk_paths: list[Path],
    start_jd: float,
    candidates_by_zone: dict[str, list[FitCenterCandidate]],
) -> None:
    """Re-fit every stale (probe, zone, chunk) and save to the cache.

    Plans are grouped by `probe_id` so multiple plans for the same probe
    (different missions / kernel sets resolved to the same probe registry
    entry; e.g. Cassini with naif=-82 from two mission dirs) MERGE into one
    `ChunkProbeRecord` per (zone, chunk): each plan furnishes its own
    kernels, fits its own contributions, and appends to a `by_chunk` dict
    that persists across all of the probe's plans. The merged record is
    then written to cache once — preventing the second plan from
    overwriting the first's data with an empty record.

    Fit-center detection runs per (probe, chunk). `fit_center_naif_by_key`
    caches the chosen center per `(zone_key, chunk_idx)`, persisting across
    plans for the same probe so one probe header encodes one center.

    Why "first wins" is correct here: a probe can have multiple flying
    contributions to the same chunk when its SPK coverage is split across
    intervals with a gap (e.g. New Horizons' Sep-2007 → Dec-2014 hole could
    produce two flying intervals that each touch the same chunk on the
    boundary). ``classify.py`` appends contributions per-interval in time
    order, so "first" is the earliest sub-window — pinning the center there
    is fine because a probe's dominant primary inside a single streaming
    chunk doesn't switch (chunks are sized below typical Hill-traversal
    timescales). Landed contributions don't consult the cache; their fit
    center is implicit in the landing body.

    Per-plan flying dedupe: when a probe has multiple plans (registry
    `kernel_sources` listing more than one mission — e.g. INTEGRAL's real
    SPK + HORIZONS-SYNTH backfill, Cassini in CASSINI + HUYGENS), each
    plan's coverage often overlaps the others'. Without dedupe both plans
    fit the same (zone, chunk) and ``rec.flying.extend`` packs **double**
    the sub-chunks (verified: INTEGRAL earth-moon chunks had 120/60
    sub-chunks). The writer's grid padder then assigns those duplicates
    adjacent slots, so the decoder reads each duplicate's payload at the
    wrong time — yields catastrophic errors. The first plan to fit a
    (zone, chunk) claims it; subsequent plans skip flying contributions
    for that key. Intra-plan gap contributions still accumulate because
    they come from the same plan.

    TODO(source-priority-for-glitchy-kernels): the multi-source probes
    can still ship bad data on specific chunks when their primary SPK
    has a brief glitch and the dedupe lets the primary win. INTEGRAL's
    ``integral_sc_ssm`` reports the spacecraft at 58e6 km from Earth for
    ~2 days around 2021-09-27, then snaps back to LEO — chunk 873 max-err
    is 6e7 km because Kepler faithfully fits the glitch. HORIZONS-SYNTH
    ``-198.bsp`` covers the same span cleanly. Two ways out: (a) reorder
    each affected probe's ``kernel_sources`` so HORIZONS-SYNTH wins and
    bump the canonical naif accordingly (registry-layer change), or
    (b) detect outlier spans in ``classify_trace`` (large jumps in r
    between consecutive samples) and drop them. Both apply to the same
    short list — INTEGRAL/-275, Cassini/-82, Venus Express/-248.
    """
    stale_by_probe: dict[int, set[tuple[str, int]]] = defaultdict(set)
    for probe_id, zone_key, chunk_idx in stale_sigs:
        stale_by_probe[probe_id].add((zone_key, chunk_idx))

    plans_by_probe: dict[int, list[ProbePlan]] = defaultdict(list)
    for p in plans:
        if p.probe_id in stale_by_probe:
            plans_by_probe[p.probe_id].append(p)

    probe_ids = sorted(plans_by_probe)
    logger.info(
        "Probes export: %d stale fits to recompute across %d probes",
        len(stale_sigs),
        len(probe_ids),
    )

    for i, probe_id in enumerate(probe_ids, 1):
        plans_for_probe = plans_by_probe[probe_id]
        stale_keys = stale_by_probe[probe_id]
        by_chunk: dict[tuple[str, int], ChunkProbeRecord] = {}
        fit_center_naif_by_key: dict[tuple[str, int], int] = {}
        # Per-key plan ownership: the first plan to fit a (zone, chunk)
        # claims it. Subsequent plans for the same probe skip flying
        # contributions to that key (see class docstring on multi-source
        # dedupe). Intra-plan gap contributions still accumulate.
        flying_owner_by_key: dict[tuple[str, int], int] = {}
        # Track which plans actually contributed flying data to each
        # (zone, chunk), so system_intervals can be drawn only from
        # plans that had coverage there (using ALL plans' intervals
        # would graft phantom system tags from plan B onto chunks only
        # covered by plan A).
        contributing_plans: dict[tuple[str, int], list[ProbePlan]] = defaultdict(list)

        for plan in plans_for_probe:
            for k in plan.kernels:
                spiceypy.furnsh(str(k))
            for p in generic_spk_paths:
                spiceypy.furnsh(str(p))
            try:
                for c in plan.contributions:
                    key = (c.zone_key, c.chunk_idx)
                    if key not in stale_keys:
                        continue
                    if c.kind == "flying":
                        owner = flying_owner_by_key.get(key)
                        if owner is not None and owner != id(plan):
                            continue
                    zone = ZONES_BY_KEY[c.zone_key]
                    chunk_start_et = (
                        jd_to_et(start_jd) + c.chunk_idx * zone.chunk_days * S_PER_DAY
                    )
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
                                probe_id=probe_id,
                                first_offset=first_offset,
                                fit_center_id_value=center_id_value,
                                fit_center_id_type=center_id_type,
                            )
                            by_chunk[key] = rec
                        rec.flying.extend(chunk_sizing.sub_chunks)
                        flying_owner_by_key.setdefault(key, id(plan))
                        if plan not in contributing_plans[key]:
                            contributing_plans[key].append(plan)
                    elif c.kind == "landed":
                        assert c.landed_body_id_value is not None
                        assert c.landed_body_id_type is not None
                        if c.static_lat_lng is not None:
                            # Events-driven landing: no SPICE, lat/lng come from
                            # the curated events JSON. Phase is implicitly static
                            # (probes that move on the surface have SPICE coverage
                            # and use the fit_landed_chunk path).
                            lat, lng = c.static_lat_lng
                            landed_fit = LandedFit(
                                body_id_value=c.landed_body_id_value,
                                body_id_type=c.landed_body_id_type,
                                is_static=True,
                                start_offset_s=int(
                                    round(c.c_start_et - chunk_start_et)
                                ),
                                end_offset_s=int(round(c.c_end_et - chunk_start_et)),
                                lat_ref_deg=lat,
                                lng_ref_deg=lng,
                                alt_ref_m=0.0,
                                samples=[],
                                peak_displacement_m=0.0,
                            )
                        else:
                            landed_fit = fit_landed_chunk(
                                probe_naif_id=plan.naif_id,
                                body_naif_id=c.landed_body_id_value,
                                chunk_start_et=chunk_start_et,
                                c_start_et=c.c_start_et,
                                c_end_et=c.c_end_et,
                            )
                        if landed_fit is None:
                            continue
                        if rec is None:
                            rec = ChunkProbeRecord(probe_id=probe_id, first_offset=0)
                            by_chunk[key] = rec
                        rec.landed = landed_fit
            finally:
                for p in generic_spk_paths:
                    spiceypy.unload(str(p))
                for k in plan.kernels:
                    spiceypy.unload(str(k))

        # System intervals: union across plans that actually contributed
        # flying data to this (zone, chunk), then clip + dedupe.
        for key, rec in by_chunk.items():
            zone_key, chunk_idx = key
            if zone_key != INTERPLANETARY.key:
                continue
            plans_here = contributing_plans.get(key, [])
            if not plans_here:
                continue
            intervals = sorted(
                {iv for plan in plans_here for iv in plan.system_intervals}
            )
            if not intervals:
                continue
            zone = ZONES_BY_KEY[zone_key]
            chunk_start_et = (
                jd_to_et(start_jd) + chunk_idx * zone.chunk_days * S_PER_DAY
            )
            chunk_end_et = chunk_start_et + zone.chunk_days * S_PER_DAY
            rec.system_intervals = _clip_system_intervals(
                intervals, chunk_start_et, chunk_end_et
            )

        for key in stale_keys:
            rec = by_chunk.get(key)
            fit_cache.save(
                probe_id,
                key[0],
                key[1],
                rec,
                stale_sigs[(probe_id, key[0], key[1])],
            )
        logger.info(
            "[%d/%d] fit probe_id=%d (%d plans) → %d/%d stale (zone, chunk) "
            "entries produced records",
            i,
            len(probe_ids),
            probe_id,
            len(plans_for_probe),
            len(by_chunk),
            len(stale_keys),
        )


def decide_dirty_chunks(
    chunk_index: dict[str, dict[int, list[ProbePlan]]],
    expected_sigs: dict[tuple[int, str, int], dict],
    metas_by_probe_id: dict[int, ProbeMeta],
    out_dir: Path,
) -> dict[str, dict[int, dict]]:
    """For each planned chunk, compute its expected chunk signature from the
    per-probe fit signatures + header bits, and compare against the on-disk sidecar.

    Per-probe block in the chunk sig carries `{fit, ord, has_loc}`:
      * `fit` — short hash of the per-probe fit signature (kernels, candidates,
        events, zone, fit_version). Flips when the trajectory itself must
        change.
      * `ord` / `has_loc` — wire-header bits (`object_type_ordinal`,
        `has_localized`). Flip when an i18n / type-tag change should repack
        the chunk binary without re-fitting the trajectory.
    """
    probes_dir = out_dir / "position" / "probes"
    dirty: dict[str, dict[int, dict]] = defaultdict(dict)
    for zone_key, chunks in chunk_index.items():
        zone_obj = ZONES_BY_KEY[zone_key]
        zone_out = probes_dir / zone_key
        for chunk_idx, plan_list in chunks.items():
            probe_block: dict[str, dict] = {}
            for p in plan_list:
                sig = expected_sigs.get((p.probe_id, zone_key, chunk_idx))
                if sig is None:
                    continue
                meta = metas_by_probe_id[p.probe_id]
                probe_block[str(p.probe_id)] = {
                    "fit": fit_cache.signature_hash(sig),
                    "ord": meta.object_type_ordinal,
                    "has_loc": meta.has_localized,
                }
            new_sig = sidecar.build_chunk_signature(zone_obj, probe_block)
            binary_path = zone_out / f"{chunk_idx}.bin.gz"
            sidecar_path = sidecar.mirror_path(zone_out / f"{chunk_idx}.meta.json")
            if binary_path.exists() and sidecar.matches(sidecar_path, new_sig):
                continue
            dirty[zone_key][chunk_idx] = new_sig
    return dirty


def collect_for_repack(
    dirty: dict[str, dict[int, dict]],
    chunk_index: dict[str, dict[int, list[ProbePlan]]],
) -> dict[str, dict[int, list[ChunkProbeRecord]]]:
    """Load cached fits for every (probe, chunk) in a dirty chunk.

    `chunk_index[zone][chunk]` appends the same `ProbePlan` once per
    contribution (classify.py:239,269), so a probe with multiple flying or
    landed contributions to the same chunk appears multiple times — dedupe
    on probe_id so we only emit one record per (probe, chunk) (the cached
    `.fit` already merges all of that probe's contributions for the chunk).
    """
    by_zone_chunk: dict[str, dict[int, list[ChunkProbeRecord]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for zone_key, chunks in dirty.items():
        for chunk_idx in chunks:
            seen: set[int] = set()
            for plan in chunk_index[zone_key][chunk_idx]:
                if plan.probe_id in seen:
                    continue
                seen.add(plan.probe_id)
                rec = fit_cache.load(plan.probe_id, zone_key, chunk_idx)
                if rec is None:
                    continue
                by_zone_chunk[zone_key][chunk_idx].append(rec)
    return by_zone_chunk
