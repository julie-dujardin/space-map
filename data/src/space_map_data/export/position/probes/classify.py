"""Pass 1 of the probes exporter: classify per-probe coverage in parallel.

Per-probe furnish + `inception_et` + `classify_trace`, parallelised across
processes. The main process owns `probe_id_cache` and plan construction so
deterministic probe-ID assignment is preserved.
"""

import logging
import multiprocessing
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import spiceypy

from space_map_data.export.position.probes.kernels import enumerate_probes
from space_map_data.export.position.probes.plan import (
    ChunkContribution,
    ProbeMeta,
    ProbePlan,
    system_naif_for_landed_body,
    zone_for_landed_body,
)
from space_map_data.export.position.probes.time_grid import (
    chunk_aligned_range,
    landed_chunk_range,
)
from space_map_data.probes.probe_id import assign, et_to_mjd
from space_map_data.probes.trace import classify_trace, inception_et
from space_map_data.probes.zones import INTERPLANETARY, ZONES_BY_KEY

logger = logging.getLogger(__name__)


def _classify_worker_init(kernel_paths: list[str]) -> None:
    """Per-worker process init: furnish LSK/PCK + generic SPKs.

    Lives for the worker's lifetime so we don't re-furnsh ~40 files on every
    task. Mission kernels still get furnshed/unloaded per-task because they
    vary per probe and a slow mission like MEX (282 BSPs) would bloat the
    per-worker kernel pool otherwise.

    LSK is required for SPK Type 10 (SGP4) kernels — e.g. HST's
    `hst_edited.bsp` — which need leap-second data to convert TLE epochs to
    ET. Without it, `spkpos(-48, ...)` silently returns NaN and the probe
    falls out of every zone, ending up incorrectly labelled interplanetary.
    """
    for p in kernel_paths:
        spiceypy.furnsh(p)


def _classify_worker(
    mission_name: str,
    kernel_paths: list[str],
    naif_id: int,
) -> dict:
    """Per-probe classification done in a worker process.

    Returns a serialisable dict — the main process owns `probe_id_cache` and
    plan construction. Possible statuses:
      * `no_coverage` — no SPK covers this naif_id
      * `ok` — payload includes `inception_et`, flying-phase zone `intervals`
        (zone_key, start_et, end_et triples), and `landed_phases` (body_naif,
        start_et, end_et triples). Either list may be empty.

    SPICE state per process: generic kernels were furnished in
    `_classify_worker_init`; mission kernels are furnshed here and unloaded
    in `finally` so the worker can move to the next mission cleanly.
    """
    for k in kernel_paths:
        spiceypy.furnsh(k)
    try:
        t0 = inception_et(naif_id, kernel_paths)
        if t0 is None:
            return {"status": "no_coverage"}
        result = classify_trace(naif_id, kernel_paths)
        return {
            "status": "ok",
            "inception_et": t0,
            "intervals": [
                (iv.zone_key, iv.start_et, iv.end_et) for iv in result.zone_intervals
            ],
            "landed_phases": [
                (p.body_naif_id, p.start_et, p.end_et) for p in result.landed_phases
            ],
        }
    finally:
        for k in kernel_paths:
            spiceypy.unload(k)


def _compute_system_intervals(
    intervals: list[tuple[str, float, float]],
    landed_phases: list[tuple[int, float, float]],
) -> list[tuple[float, float, int]]:
    """Derive per-time-span 'containing planet system NAIF' annotations from
    a probe's classified trace.

    Combines flying spans inside planetary zones (zone.barycenter_naif_id)
    with landed phases (body→system map). Adjacent same-system spans are
    merged so the writer emits one interval per continuous Mars/Jupiter/…
    presence instead of N tiny tiles. Returns intervals sorted by start_et,
    non-overlapping (assuming the input zone_intervals are non-overlapping
    within each zone, which `_classify_flying_subrange` guarantees).
    """
    raw: list[tuple[float, float, int]] = []
    for zone_key, s, e in intervals:
        if zone_key == INTERPLANETARY.key:
            continue
        zone = ZONES_BY_KEY.get(zone_key)
        if zone is None:
            continue
        raw.append((float(s), float(e), int(zone.barycenter_naif_id)))
    for body_naif, s, e in landed_phases:
        sys_naif = system_naif_for_landed_body(int(body_naif))
        if sys_naif is None:
            continue
        raw.append((float(s), float(e), int(sys_naif)))
    if not raw:
        return []
    raw.sort()
    merged: list[list[float | int]] = [list(raw[0])]
    for s, e, sn in raw[1:]:
        last = merged[-1]
        if sn == last[2] and s <= last[1]:
            last[1] = max(last[1], e)
        else:
            merged.append([s, e, sn])
    return [(float(s), float(e), int(sn)) for s, e, sn in merged]


def classify_pass(
    probe_registry: list[dict],
    probe_source_index: dict[tuple[str, int], dict],
    metas_by_probe_id: dict[int, ProbeMeta],
    lsk_pck_paths: list[Path],
    generic_spk_paths: list[Path],
    start_jd: float,
) -> tuple[list[ProbePlan], dict[str, dict[int, list[ProbePlan]]]]:
    """Pass 1: per-probe furnish + classify, parallelised across processes.

    SPICE state is per-process, so each worker gets its own kernel pool —
    no contention with the parent and no GIL bottleneck on the spkpos loop.
    `probe_id` assignment runs serially in the main process because
    `probe_registry`/`probe_source_index` are mutated as new probes get
    registered and the order in which IDs are allocated must match the
    deterministic `(inception_mjd, naif_id)` policy in `probes.probe_id.assign`.

    Furnsh order per probe: mission first (in worker), then generic SPKs
    (pre-furnshed via initializer) — so modern planetary ephemerides win
    over any planetary data bundled inside a mission kernel.
    """
    probes_raw = enumerate_probes()
    n_probes = len(probes_raw)
    n_workers = max(1, min(8, multiprocessing.cpu_count() // 2))
    logger.info(
        "Probes export: %d spacecraft to classify across %d workers",
        n_probes,
        n_workers,
    )

    plans: list[ProbePlan] = []
    chunk_index: dict[str, dict[int, list[ProbePlan]]] = defaultdict(
        lambda: defaultdict(list)
    )

    # LSK first so SPK Type 10 (SGP4) probes — HST's hst_edited.bsp uses
    # this format — can convert TLE epochs to ET; PCK for body-fixed-frame
    # lookups in landed detection; generic SPKs for planet ephemerides.
    init_paths = [str(p) for p in (lsk_pck_paths + generic_spk_paths)]
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_classify_worker_init,
        initargs=(init_paths,),
    ) as ex:
        futures = {}
        for i, (mdir, kernels, naif_id) in enumerate(probes_raw, 1):
            kpaths = [str(k) for k in kernels]
            fut = ex.submit(_classify_worker, mdir.name, kpaths, naif_id)
            futures[fut] = (i, mdir, kernels, naif_id)

        for fut in as_completed(futures):
            i, mdir, kernels, naif_id = futures[fut]
            try:
                result = fut.result()
            except Exception:
                logger.exception(
                    "[%d/%d] classify worker failed for %s naif=%d",
                    i,
                    n_probes,
                    mdir.name,
                    naif_id,
                )
                continue

            if result["status"] == "no_coverage":
                logger.warning("no coverage for %s/%d", mdir.name, naif_id)
                continue

            t0 = result["inception_et"]
            rec = assign(
                mission=mdir.name,
                naif_id=naif_id,
                inception_mjd=et_to_mjd(t0),
                registry=probe_registry,
                source_index=probe_source_index,
            )
            probe_id = rec.probe_id
            if probe_id not in metas_by_probe_id:
                logger.warning(
                    "no Object row for probe_id=%d (mission=%s naif=%d); "
                    "run ingest first",
                    probe_id,
                    mdir.name,
                    naif_id,
                )
                continue

            landed_phases = result.get("landed_phases", [])
            plan = ProbePlan(
                probe_id=probe_id,
                naif_id=naif_id,
                kernels=kernels,
                system_intervals=_compute_system_intervals(
                    result["intervals"], landed_phases
                ),
            )
            for zone_key, iv_start, iv_end in result["intervals"]:
                zone = ZONES_BY_KEY[zone_key]
                for chunk_idx, c_start, c_end in chunk_aligned_range(
                    zone.chunk_years,
                    zone.kepler_subchunk_days,
                    iv_start,
                    iv_end,
                    start_jd,
                ):
                    plan.contributions.append(
                        ChunkContribution(zone_key, chunk_idx, c_start, c_end)
                    )
                    chunk_index[zone_key][chunk_idx].append(plan)
            # Landed phases — each gets one trailing `METHOD_LANDED` record
            # per streaming chunk it overlaps. Routes to the body's parent
            # planet zone (Mars 499 → mars zone, Titan 606 → saturn, …).
            for body_naif, ph_start, ph_end in landed_phases:
                zone = zone_for_landed_body(int(body_naif))
                if zone is None:
                    logger.warning(
                        "no zone mapping for landed body %d on probe %s/%d; "
                        "phase %.0f→%.0f dropped",
                        body_naif,
                        mdir.name,
                        naif_id,
                        ph_start,
                        ph_end,
                    )
                    continue
                for chunk_idx, c_start, c_end in landed_chunk_range(
                    zone.chunk_years, ph_start, ph_end, start_jd
                ):
                    contrib = ChunkContribution(
                        zone_key=zone.key,
                        chunk_idx=chunk_idx,
                        c_start_et=c_start,
                        c_end_et=c_end,
                        kind="landed",
                        landed_body_naif_id=int(body_naif),
                    )
                    plan.contributions.append(contrib)
                    chunk_index[zone.key][chunk_idx].append(plan)
            plans.append(plan)
            logger.info(
                "[%d/%d] %s naif=%d probe_id=%d (%d intervals, %d chunk-touches, "
                "%d landed phases)",
                i,
                n_probes,
                mdir.name,
                naif_id,
                probe_id,
                len(result["intervals"]),
                len(plan.contributions),
                len(landed_phases),
            )

    return plans, chunk_index
