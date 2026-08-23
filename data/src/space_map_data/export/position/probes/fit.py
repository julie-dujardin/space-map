"""Pass 2 of the probes exporter: per-probe fit cache + chunk dirty check.

Two sub-passes:

  * ``stale_fits`` + ``build_fits`` — per-probe granularity. Each (probe,
    zone, chunk) contribution gets a signature over just that probe's
    inputs (kernels + the zone/candidates/events hashes it depends on). A
    cache match skips the expensive ``size_chunk``/``fit_landed_chunk``
    work; a miss re-furnishes, re-fits, and saves the result.

  * ``decide_dirty_chunks`` + ``collect_for_repack`` — chunk granularity.
    The chunk sidecar records each contributing probe's fit-signature hash;
    a mismatch means loading every contributing probe's cached fit for the
    write pass.

This split decouples "a probe's inputs changed" from "this chunk needs
rewriting": a kernel edit on Voyager 2 only re-fits Voyager 2, even when its
interplanetary chunks are shared with Voyager 1, Pioneer, etc.
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
    detect_nearest_center,
    fit_center_header_fields,
)
from space_map_data.probes.small_bodies import SMALL_BODY_ZONE_RADIUS_KM
from space_map_data.probes.zones import INTERPLANETARY, SMALL_BODIES, ZONES_BY_KEY

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
    contribution in `plans` — see `fit_cache.build_fit_signature`.

    When multiple plans share a probe_id (Cassini classified across two
    mission dirs), the kernel list folded in is the union of all plans'
    kernels, matching what `build_fits` will actually furnish.
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
    canonical_naif_by_probe_id: dict[int, int],
) -> None:
    """Re-fit every stale (probe, zone, chunk) and save to the cache.

    Plans are grouped by `probe_id`: multiple plans for the same probe
    (e.g. Cassini naif=-82 classified across two mission dirs) MERGE into
    one `ChunkProbeRecord` per (zone, chunk) via a `by_chunk` dict shared
    across the probe's plans, written once so a later plan can't overwrite
    an earlier one's data with an empty record.

    Fit-center detection runs per (probe, chunk); `fit_center_naif_by_key`
    caches the chosen center per key so one probe header encodes one center.
    "First wins" is correct because a probe's dominant primary doesn't
    switch within a single streaming chunk (chunks are sized below typical
    Hill-traversal timescales) — so pinning the center at the earliest
    sub-window covering a split-coverage chunk (e.g. New Horizons'
    Sep-2007→Dec-2014 gap) is safe. Landed contributions don't consult the
    cache; their fit center is implicit in the landing body.

    Per-plan flying dedupe: a probe with multiple plans (INTEGRAL's real SPK
    + HORIZONS-SYNTH backfill, Cassini in CASSINI + HUYGENS) often has
    overlapping plan coverage. Without dedupe, both plans fit the same
    (zone, chunk) and `rec.flying.extend` doubles the sub-chunks — the
    writer's grid padder then puts the decoder out of sync with catastrophic
    errors (verified on INTEGRAL earth-moon chunks). The first plan to fit a
    (zone, chunk) claims it; later plans skip flying contributions there.
    Intra-plan gap contributions still accumulate. Plans are sorted so the
    plan whose naif matches the registry-canonical `naif_id` claims first:
    plan arrival order is `as_completed` (nondeterministic), and for a
    QID-merged spacecraft PAIR like M-MATISSE (Henri -101 / Marguerite
    -102, ~15,000 km apart) the loser of that race once shipped — while
    the benchmark evaluates the canonical naif, reporting the whole fit as
    a systematic inter-spacecraft offset.

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
        canonical_naif = canonical_naif_by_probe_id.get(probe_id)
        plans_for_probe = sorted(
            plans_by_probe[probe_id],
            key=lambda p: (
                p.naif_id != canonical_naif,
                str(p.kernels[0]) if p.kernels else "",
            ),
        )
        stale_keys = stale_by_probe[probe_id]
        by_chunk: dict[tuple[str, int], ChunkProbeRecord] = {}
        # None = small-bodies chunk with no matchable target; skip its
        # contributions instead of falling back to a Sun-relative fit.
        fit_center_naif_by_key: dict[tuple[str, int], int | None] = {}
        # First plan to fit a (zone, chunk) claims it — see build_fits
        # docstring on multi-source dedupe.
        flying_owner_by_key: dict[tuple[str, int], int] = {}
        # Plans that actually contributed flying data per (zone, chunk), so
        # system_intervals draws only from plans with real coverage there.
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
                        if key not in fit_center_naif_by_key:
                            if zone.key == SMALL_BODIES.key:
                                # Nearest-target attachment, and never the
                                # zone default: a Sun-relative record in this
                                # f32 zone would quantize at ~10 km, so a
                                # chunk with no matchable body is dropped.
                                chosen = detect_nearest_center(
                                    candidates_by_zone.get(c.zone_key, []),
                                    plan.naif_id,
                                    c.c_start_et,
                                    c.c_end_et,
                                    SMALL_BODY_ZONE_RADIUS_KM,
                                )
                                if chosen is None:
                                    logger.warning(
                                        "small-bodies chunk %s for naif=%d has "
                                        "no matchable target; dropped",
                                        key,
                                        plan.naif_id,
                                    )
                            else:
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
                            fit_center_naif_by_key[key] = (
                                None
                                if chosen is None and zone.key == SMALL_BODIES.key
                                else center_naif
                            )
                            if fit_center_naif_by_key[key] is None:
                                continue
                        else:
                            cached_center = fit_center_naif_by_key[key]
                            if cached_center is None:
                                continue
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
                            # Events-driven landing: static lat/lng, no SPICE.
                            # Probes that move on the surface have SPICE
                            # coverage instead, via fit_landed_chunk.
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
    per-probe fit signatures + header bits, and compare against the on-disk
    sidecar.

    Per-probe block carries `{fit, ord, has_loc}`: `fit` is a short hash of
    the per-probe fit signature, flipping when the trajectory must change;
    `ord`/`has_loc` are wire-header bits that flip on an i18n/type-tag
    change, repacking the binary without re-fitting.
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
    contribution, so a probe with multiple contributions to the same chunk
    appears multiple times — dedupe on probe_id, since the cached `.fit`
    already merges all of that probe's contributions.
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
