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
chunk index for a given JD is `floor((jd - start_jd) / chunk_years / 365.25)`,
matching the chebyshev exporter's convention.

Incremental: each chunk emits a JSON sidecar with `(fit_version, zone_hash,
probes→kernel mtime+size)`. On re-export we recompute that signature and
skip the chunk if it matches what's on disk. See `sidecar.py`.
"""

import gzip
import json
import logging
import math
import multiprocessing
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import spiceypy
from sqlalchemy import select
from sqlalchemy.orm import Session

from space_map_data.constants.providers import PROVIDERS
from space_map_data.download.providers.objects.probes import MISSIONS_DIR
from space_map_data.export.position.format import (
    METHOD_CHEBYSHEV,
    METHOD_KEPLER_DRIFT,
    METHOD_KEPLER_PURE,
    METHOD_UNCOVERABLE,
    OBJECT_TYPE_ORDINAL,
    pack_probe_header,
    pack_probes_header,
    pack_subchunk_record,
)
from space_map_data.export.position.probes import sidecar
from space_map_data.export.position.probes.sizing import (
    METHOD_CHEBYSHEV as SZ_METHOD_CHEBYSHEV,
    METHOD_KEPLER_DRIFT as SZ_METHOD_KEPLER_DRIFT,
    METHOD_KEPLER_PURE as SZ_METHOD_KEPLER_PURE,
    METHOD_UNCOVERABLE as SZ_METHOD_UNCOVERABLE,
    SubChunkFit,
    size_chunk,
)
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.probes.probe_id import (
    _load_cache as _load_probe_id_cache,
    assign,
    et_to_mjd,
)
from space_map_data.probes.trace import classify_trace, inception_et
from space_map_data.probes.zones import ALL_ZONES, ZONES_BY_KEY, Zone

logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0

# Chunk grid anchor — chebyshev uses 1950-01-01, we share it. End year is
# bumped past chebyshev's 2050 because predicted-ephemeris kernels reach
# well into the late 21st century (Voyager Interstellar Mission kernels go
# to ~2120, JWST predicted to ~2050, HERA / SOLAR-ORBITER predict to 2030+).
# Setting end past every kernel keeps the manifest's `chunks` count an
# upper bound on the max chunk index the writer can emit.
_PROBE_EXPORT_START_YEAR = 1950
_PROBE_EXPORT_END_YEAR = 2150

# Kernels we never furnish: stationary post-mission ephemerides extend
# coverage by decades at fixed coords and corrupt zone classification.
_STATIONARY_PATTERNS = ("_imp_", "_crashsite_")

_METHOD_ORDINAL = {
    SZ_METHOD_KEPLER_PURE: METHOD_KEPLER_PURE,
    SZ_METHOD_KEPLER_DRIFT: METHOD_KEPLER_DRIFT,
    SZ_METHOD_CHEBYSHEV: METHOD_CHEBYSHEV,
    SZ_METHOD_UNCOVERABLE: METHOD_UNCOVERABLE,
}


def _year_to_jd(year: int) -> float:
    """Civil-year start (Jan 1) → Julian Date TDB (matching chebyshev writer)."""
    import datetime

    d = datetime.date(year, 1, 1)
    return d.toordinal() + 1721424.5


def _et_to_jd(et: float) -> float:
    return _J2000_JD + et / _S_PER_DAY


def _jd_to_et(jd: float) -> float:
    return (jd - _J2000_JD) * _S_PER_DAY


def _mission_kernels(mdir: Path) -> list[Path]:
    return [
        k
        for k in (sorted(mdir.glob("*.bsp")) + sorted(mdir.glob("*.BSP")))
        if not any(p in k.name for p in _STATIONARY_PATTERNS)
    ]


def _collect_generic_kernels(
    kernels_dir: Path,
) -> tuple[list[Path], list[Path]]:
    """Collect generic kernels under `kernels/`, splitting them by role.

    Returns `(lsk_pck_paths, generic_spk_paths)`:
      * LSK (.tls) / PCK (.tpc) — leapseconds and physical constants. No SPK
        precedence implications; load once at outer scope.
      * Generic SPKs (.bsp under `spk/`) — planetary ephemerides (de440,
        sat441, …). Must be furnshed AFTER mission kernels so they win for
        shared targets (Saturn 699, Saturn-barycenter 6, etc.). Mission
        kernels like p11-a.bsp embed their own 1970s-era planetary data,
        which would otherwise contaminate the fit.

    `missions/` and `probes/` subtrees are excluded (handled per-probe).
    """
    skip_dirs = {"missions", "probes"}
    lsk_pck: list[Path] = []
    generic_spk: list[Path] = []
    for path in sorted(kernels_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(kernels_dir).parts):
            continue
        suffix = path.suffix.lower()
        if suffix in (".tls", ".tpc"):
            lsk_pck.append(path)
        elif suffix == ".bsp":
            generic_spk.append(path)
    return lsk_pck, generic_spk


@dataclass(frozen=True)
class _ProbeMeta:
    """Per-probe info needed at pack time."""

    probe_id: int
    obj_id: str
    object_type_ordinal: int
    has_localized: bool


@dataclass(frozen=True)
class _ChunkContribution:
    """One probe's contribution to one (zone, chunk_idx): the time slice
    it covers, aligned to the sub-chunk grid."""

    zone_key: str
    chunk_idx: int
    c_start_et: float
    c_end_et: float


@dataclass
class _ProbePlan:
    """All chunks one probe touches + the kernels needed to fit them.
    Built in the classify pass; consumed in the fit pass."""

    probe_id: int
    naif_id: int
    kernels: list[Path]
    contributions: list[_ChunkContribution] = field(default_factory=list)


def _chunk_aligned_range(
    chunk_years: float,
    subchunk_days: float,
    t_start_et: float,
    t_end_et: float,
    start_jd_anchor: float,
) -> list[tuple[int, float, float]]:
    """Return `[(chunk_idx, sub_t_start_et, sub_t_end_et), ...]` covering
    `[t_start_et, t_end_et]`, where the returned `(s, e)` snap to the
    SUB-CHUNK grid anchored at `chunk_start_et`.

    Snapping matters: the binary's `first_subchunk_offset` is an integer
    sub-chunk index, so sub-chunk boundaries must land on
    `chunk_start_et + k * sub_s` exactly. Without the snap the fits would
    happen on interval-aligned windows but the binary would record them on
    chunk-aligned indices, drifting up to half a sub_s — millions of km of
    phase error on cruise probes.

    Loses up to one sub_s per interval boundary (coverage trailing past
    the last grid point gets dropped), which is at most a few days even
    for interplanetary (7-day sub-chunks).
    """
    chunk_s = chunk_years * 365.25 * _S_PER_DAY
    sub_s = subchunk_days * _S_PER_DAY
    start_et_anchor = _jd_to_et(start_jd_anchor)
    first_idx = int(math.floor((t_start_et - start_et_anchor) / chunk_s))
    last_idx = int(math.ceil((t_end_et - start_et_anchor) / chunk_s))
    subs_per_chunk = int(chunk_s / sub_s)
    out: list[tuple[int, float, float]] = []
    for idx in range(first_idx, last_idx):
        cs = start_et_anchor + idx * chunk_s
        s_offset = max(0, int(math.ceil((t_start_et - cs) / sub_s)))
        e_offset = min(subs_per_chunk, int(math.floor((t_end_et - cs) / sub_s)))
        if s_offset >= e_offset:
            continue
        s = cs + s_offset * sub_s
        e = cs + e_offset * sub_s
        out.append((idx, s, e))
    return out


def _pack_kepler_payload(
    elts: dict, method: str, float64: bool, sub_t_start_et: float
) -> bytes:
    """Pack Kepler elements + anchor offset. Pure = 7 values, drift = 10.

    Field order MUST match the frontend parser:
      pure : a_km, e, i_rad, om0, w0, m0, t_anchor_offset_s
      drift: a_km, e, i_rad, om0, w0, m0, om_dot, w_dot, n_mean_rad_s, t_anchor_offset_s

    `t_anchor_offset_s = t_snap_et - sub_t_start_et` lets the consumer
    reconstruct the snapshot epoch (which is *not* the sub-chunk start —
    the fitter anchors at the closest valid sample to the sub-chunk
    midpoint, drifting by up to ~half a fit-window from the start).
    """
    t_anchor_offset_s = elts["t_mid"] - sub_t_start_et
    base = [
        elts["a_km"],
        elts["e"],
        elts["i_rad"],
        elts["om0"],
        elts["w0"],
        elts["m0"],
    ]
    if method == SZ_METHOD_KEPLER_DRIFT:
        base.extend([elts["om_dot"], elts["w_dot"], elts["n_mean_rad_s"]])
    base.append(t_anchor_offset_s)
    dtype = np.float64 if float64 else np.float32
    return np.asarray(base, dtype=dtype).tobytes()


def _pack_chebyshev_payload(coeffs: np.ndarray, float64: bool) -> bytes:
    """Pack `(n_seg, 3, degree+1)` coefficients as a flat dtype array.

    Segment time bounds are not stored — they're implicit from the sub-chunk
    start + `subchunk_days` from the chunk-level header divided by `n_seg`.
    The frontend recovers per-segment bounds at parse time.
    """
    dtype = np.float64 if float64 else np.float32
    return np.ascontiguousarray(coeffs, dtype=dtype).tobytes()


def _pack_subchunk(fit: SubChunkFit, zone: Zone) -> bytes:
    """Pack one sub-chunk fit (method byte + payload) into bytes."""
    ordinal = _METHOD_ORDINAL[fit.method]
    if fit.method in (SZ_METHOD_KEPLER_PURE, SZ_METHOD_KEPLER_DRIFT):
        assert fit.kepler_elts is not None  # invariant: kepler methods set this
        payload = _pack_kepler_payload(
            fit.kepler_elts, fit.method, zone.float64_coeffs, fit.t_start_et
        )
    elif fit.method == SZ_METHOD_CHEBYSHEV:
        assert fit.chebyshev_coeffs is not None  # invariant: chebyshev sets coeffs
        payload = _pack_chebyshev_payload(fit.chebyshev_coeffs, zone.float64_coeffs)
    else:
        payload = b""
    return pack_subchunk_record(ordinal, payload)


def _enumerate_probes() -> list[tuple[Path, list[Path], int]]:
    """Walk `missions/` and return `[(mission_dir, kernels, naif_id)]` for
    every spacecraft NAIF ID in `[-999, -1]`, after dropping stationary
    kernels.

    Kernels come from `_index.json`'s `files` list (whatever MISSION_INCLUDE
    matched at download time), NOT a directory glob. Globbing would pick up
    stale or downloader-filtered BSPs left over from prior downloads — e.g.
    MEX's 269 ORMM monthly kernels that we now exclude because their segment
    count thrashes SPICE's DAF cache.
    """
    out: list[tuple[Path, list[Path], int]] = []
    if not MISSIONS_DIR.exists():
        return out
    for mdir in sorted(MISSIONS_DIR.iterdir()):
        if not mdir.is_dir():
            continue
        idx_path = mdir / "_index.json"
        if not idx_path.exists():
            continue
        idx = json.loads(idx_path.read_text())
        kernels = [
            mdir / f["name"]
            for f in idx.get("files", [])
            if (mdir / f["name"]).exists()
            and not any(p in f["name"] for p in _STATIONARY_PATTERNS)
        ]
        if not kernels:
            continue
        spacecraft_ids = sorted(
            t for t in (int(s) for s in idx.get("targets", {})) if -999 <= t <= -1
        )
        for naif_id in spacecraft_ids:
            out.append((mdir, kernels, naif_id))
    return out


def _build_probe_metas(
    session: Session, has_localized: dict[str, bool]
) -> dict[int, _ProbeMeta]:
    """Map probe_id → _ProbeMeta for every probe Object row in the DB."""
    rows = session.execute(
        select(Object.id, Object.probe_id, Object.object_type).where(
            Object.orbital_source == OrbitalSource.spice_probe
        )
    ).all()
    metas: dict[int, _ProbeMeta] = {}
    for row in rows:
        if row.probe_id is None:
            continue
        metas[row.probe_id] = _ProbeMeta(
            probe_id=row.probe_id,
            obj_id=row.id,
            object_type_ordinal=OBJECT_TYPE_ORDINAL.get(row.object_type, 255),
            has_localized=bool(has_localized.get(row.id, False)),
        )
    return metas


def _classify_worker_init(generic_spk_paths: list[str]) -> None:
    """Per-worker process init: furnish generic kernels (LSK/PCK/DE/sat).

    Generics live for the worker's lifetime so we don't re-furnsh ~40 files
    on every task. Mission kernels still get furnshed/unloaded per-task
    because they vary per probe and a slow mission like MEX (282 BSPs)
    would bloat the per-worker kernel pool otherwise.
    """
    for p in generic_spk_paths:
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


def _classify_pass(
    probe_id_cache: dict,
    metas_by_probe_id: dict[int, _ProbeMeta],
    generic_spk_paths: list[Path],
    start_jd: float,
) -> tuple[list[_ProbePlan], dict[str, dict[int, list[_ProbePlan]]]]:
    """Pass 1: per-probe furnish + classify, parallelised across processes.

    SPICE state is per-process, so each worker gets its own kernel pool —
    no contention with the parent and no GIL bottleneck on the spkpos loop.
    `probe_id` assignment runs serially in the main process because
    `probe_id_cache` is mutable and the order in which IDs are allocated
    must match the deterministic `(inception_mjd, naif_id)` policy in
    `probes.probe_id.assign`.

    Furnsh order per probe: mission first (in worker), then generic SPKs
    (pre-furnshed via initializer) — so modern planetary ephemerides win
    over any planetary data bundled inside a mission kernel.
    """
    probes_raw = _enumerate_probes()
    n_probes = len(probes_raw)
    n_workers = max(1, min(8, multiprocessing.cpu_count() // 2))
    logger.info(
        "Probes export: %d spacecraft to classify across %d workers",
        n_probes,
        n_workers,
    )

    plans: list[_ProbePlan] = []
    chunk_index: dict[str, dict[int, list[_ProbePlan]]] = defaultdict(
        lambda: defaultdict(list)
    )

    generic_str = [str(p) for p in generic_spk_paths]
    with ProcessPoolExecutor(
        max_workers=n_workers,
        initializer=_classify_worker_init,
        initargs=(generic_str,),
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
                cache=probe_id_cache,
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

            plan = _ProbePlan(probe_id=probe_id, naif_id=naif_id, kernels=kernels)
            for zone_key, iv_start, iv_end in result["intervals"]:
                zone = ZONES_BY_KEY[zone_key]
                for chunk_idx, c_start, c_end in _chunk_aligned_range(
                    zone.chunk_years,
                    zone.kepler_subchunk_days,
                    iv_start,
                    iv_end,
                    start_jd,
                ):
                    plan.contributions.append(
                        _ChunkContribution(zone_key, chunk_idx, c_start, c_end)
                    )
                    chunk_index[zone_key][chunk_idx].append(plan)
            plans.append(plan)
            # TODO(landed-export): classify_trace returns landed phases too
            # (`result["landed_phases"]` = list of (body_naif, start_et,
            # end_et) triples) — surface them in a `landed/{body}.json.gz`
            # output once the frontend's lat/lng pin renderer is ready.
            # Detection is correct as of this pass; we just don't ship.
            landed_phases = result.get("landed_phases", [])
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


def _decide_dirty(
    chunk_index: dict[str, dict[int, list[_ProbePlan]]],
    metas_by_probe_id: dict[int, _ProbeMeta],
    out_dir: Path,
    download_dir: Path,
) -> dict[str, dict[int, dict]]:
    """For each planned chunk, compute its expected signature and compare
    against the on-disk sidecar. Returns `dirty[zone][chunk_idx] = signature`
    for chunks that need re-fitting."""
    probes_dir = out_dir / "position" / "probes"
    dirty: dict[str, dict[int, dict]] = defaultdict(dict)
    for zone_key, chunks in chunk_index.items():
        zone_obj = ZONES_BY_KEY[zone_key]
        zone_out = probes_dir / zone_key
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
                zone_obj, probes_for_sig, download_dir
            )
            binary_path = zone_out / f"{chunk_idx}.bin.gz"
            sidecar_path = zone_out / f"{chunk_idx}.meta.json"
            if binary_path.exists() and sidecar.matches(sidecar_path, new_sig):
                continue
            dirty[zone_key][chunk_idx] = new_sig
    return dirty


def _fit_pass(
    plans: list[_ProbePlan],
    dirty: dict[str, dict[int, dict]],
    generic_spk_paths: list[Path],
    start_jd: float,
) -> dict[str, dict[int, list[tuple[int, int, list[SubChunkFit]]]]]:
    """Pass 2: re-furnish each probe that touches at least one dirty chunk,
    run `size_chunk` for those (probe, chunk) pairs only.

    Furnsh order matches pass 1: mission first, then generic SPKs.

    Returns `by_zone_chunk[zone][chunk_idx] = [(probe_id, first_offset,
    sub_chunks), …]`, packing-ready."""
    by_zone_chunk: dict[str, dict[int, list[tuple[int, int, list[SubChunkFit]]]]] = (
        defaultdict(lambda: defaultdict(list))
    )

    probes_with_dirty: list[_ProbePlan] = [
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
            n_fit = 0
            for c in plan.contributions:
                if c.chunk_idx not in dirty.get(c.zone_key, {}):
                    continue
                zone = ZONES_BY_KEY[c.zone_key]
                sub_s = zone.kepler_subchunk_days * _S_PER_DAY
                chunk_sizing = size_chunk(plan.naif_id, zone, c.c_start_et, c.c_end_et)
                if not chunk_sizing.sub_chunks:
                    continue
                chunk_start_et = (
                    _jd_to_et(start_jd)
                    + c.chunk_idx * zone.chunk_years * 365.25 * _S_PER_DAY
                )
                first_offset = int(
                    round(
                        (chunk_sizing.sub_chunks[0].t_start_et - chunk_start_et) / sub_s
                    )
                )
                by_zone_chunk[c.zone_key][c.chunk_idx].append(
                    (plan.probe_id, first_offset, list(chunk_sizing.sub_chunks))
                )
                n_fit += 1
            logger.info(
                "[%d/%d] fit probe_id=%d naif=%d → %d dirty (zone, chunk) entries",
                i,
                len(probes_with_dirty),
                plan.probe_id,
                plan.naif_id,
                n_fit,
            )
        finally:
            for p in generic_spk_paths:
                spiceypy.unload(str(p))
            for k in plan.kernels:
                spiceypy.unload(str(k))

    return by_zone_chunk


def _write_pass(
    chunk_index: dict[str, dict[int, list[_ProbePlan]]],
    dirty: dict[str, dict[int, dict]],
    by_zone_chunk: dict[str, dict[int, list[tuple[int, int, list[SubChunkFit]]]]],
    metas_by_probe_id: dict[int, _ProbeMeta],
    out_dir: Path,
    start_jd: float,
    end_jd: float,
) -> dict[str, dict]:
    """Pass 3: serialize dirty chunks (binary + sidecar, atomic), and build
    the manifest for every zone with at least one planned chunk."""
    probes_dir = out_dir / "position" / "probes"
    manifest: dict[str, dict] = {}
    for zone in ALL_ZONES:
        zone_key = zone.key
        all_chunks = chunk_index.get(zone_key)
        if not all_chunks:
            continue
        zone_out = probes_dir / zone_key
        zone_out.mkdir(parents=True, exist_ok=True)

        n_emit = 0
        n_skip = 0
        total_bytes = 0
        for chunk_idx in sorted(all_chunks):
            binary_path = zone_out / f"{chunk_idx}.bin.gz"
            sidecar_path = zone_out / f"{chunk_idx}.meta.json"

            if chunk_idx not in dirty.get(zone_key, {}):
                n_skip += 1
                if binary_path.exists():
                    total_bytes += binary_path.stat().st_size
                continue

            probe_records = by_zone_chunk.get(zone_key, {}).get(chunk_idx, [])
            if not probe_records:
                logger.warning(
                    "probes/%s/%d: dirty but fit yielded zero probes; leaving "
                    "any prior binary in place",
                    zone_key,
                    chunk_idx,
                )
                continue

            probe_records.sort(key=lambda r: r[0])
            chunk_start_jd = start_jd + chunk_idx * zone.chunk_years * 365.25
            chunk_end_jd = chunk_start_jd + zone.chunk_years * 365.25

            buf: list[bytes] = [
                pack_probes_header(
                    start_jd=chunk_start_jd,
                    end_jd=chunk_end_jd,
                    probe_count=len(probe_records),
                    subchunk_days=zone.kepler_subchunk_days,
                )
            ]
            for probe_id, first_offset, sub_chunks in probe_records:
                meta = metas_by_probe_id[probe_id]
                buf.append(
                    pack_probe_header(
                        probe_id=meta.probe_id,
                        object_type_ordinal=meta.object_type_ordinal,
                        has_localized=meta.has_localized,
                        n_subchunks=len(sub_chunks),
                        first_subchunk_offset=first_offset,
                    )
                )
                for sc in sub_chunks:
                    buf.append(_pack_subchunk(sc, zone))
            compressed = gzip.compress(b"".join(buf))
            sidecar.write_atomic(binary_path, compressed)
            sidecar.write_sidecar(sidecar_path, dirty[zone_key][chunk_idx])
            total_bytes += len(compressed)
            n_emit += 1

        total_window_chunks = max(
            1, math.ceil((end_jd - start_jd) / (zone.chunk_years * 365.25))
        )
        present = n_emit + n_skip
        avg_kb = (total_bytes // present) // 1024 if present else 0
        logger.info(
            "  probes/%s: %d re-fit + %d cached chunks (of %d window), "
            "avg %d KB/chunk, %.1f MB total",
            zone_key,
            n_emit,
            n_skip,
            total_window_chunks,
            avg_kb,
            total_bytes / 1024 / 1024,
        )
        manifest[f"probes/{zone_key}"] = {
            "chunks": total_window_chunks,
            "chunk_years": zone.chunk_years,
            "start_jd": start_jd,
            "end_jd": end_jd,
            "subchunk_days": zone.kepler_subchunk_days,
            "float64_coeffs": zone.float64_coeffs,
            "fit_center_naif_id": zone.fit_center_naif_id,
        }

    return manifest


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

    Returns `{zone_key_with_prefix: {chunks, chunk_years, start_jd, end_jd}}`
    so `_build_position_metadata` can fold it into the manifest.
    """
    if not MISSIONS_DIR.exists():
        logger.info("No probe missions at %s, skipping probe export", MISSIONS_DIR)
        return {}

    probe_id_cache = _load_probe_id_cache()
    metas_by_probe_id = _build_probe_metas(session, has_localized)
    start_jd = _year_to_jd(_PROBE_EXPORT_START_YEAR)
    end_jd = _year_to_jd(_PROBE_EXPORT_END_YEAR)

    lsk_pck_paths, generic_spk_paths = _collect_generic_kernels(
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

    try:
        plans, chunk_index = _classify_pass(
            probe_id_cache, metas_by_probe_id, generic_spk_paths, start_jd
        )
        dirty = _decide_dirty(chunk_index, metas_by_probe_id, out_dir, download_dir)
        by_zone_chunk = _fit_pass(plans, dirty, generic_spk_paths, start_jd)
    finally:
        spiceypy.kclear()

    return _write_pass(
        chunk_index,
        dirty,
        by_zone_chunk,
        metas_by_probe_id,
        out_dir,
        start_jd,
        end_jd,
    )
