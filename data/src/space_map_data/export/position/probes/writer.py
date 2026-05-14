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
"""

import gzip
import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
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
from space_map_data.models.object import Object, OrbitalSource
from space_map_data.probes.probe_id import (
    _load_cache as _load_probe_id_cache,
    assign,
    et_to_mjd,
)
from space_map_data.export.position.probes.sizing import (
    METHOD_CHEBYSHEV as SZ_METHOD_CHEBYSHEV,
    METHOD_KEPLER_DRIFT as SZ_METHOD_KEPLER_DRIFT,
    METHOD_KEPLER_PURE as SZ_METHOD_KEPLER_PURE,
    METHOD_UNCOVERABLE as SZ_METHOD_UNCOVERABLE,
    SubChunkFit,
    size_chunk,
)
from space_map_data.probes.trace import _coverage, classify_trace, is_landed_probe
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


def _furnish_generic_kernels(kernels_dir: Path) -> int:
    """Load every LSK / PCK / generic SPK under `kernels/`, skipping the
    `missions/` and `probes/` subtrees (mission kernels are furnished per
    probe to keep the pool small)."""
    skip_dirs = {"missions", "probes"}
    n = 0
    for path in sorted(kernels_dir.rglob("*")):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(kernels_dir).parts):
            continue
        if path.suffix.lower() in (".bsp", ".tls", ".tpc"):
            spiceypy.furnsh(str(path))
            n += 1
    return n


@dataclass(frozen=True)
class _ProbeMeta:
    """Per-probe info needed at pack time."""

    probe_id: int
    obj_id: str
    object_type_ordinal: int
    has_localized: bool


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
    kernels."""
    out: list[tuple[Path, list[Path], int]] = []
    if not MISSIONS_DIR.exists():
        return out
    for mdir in sorted(MISSIONS_DIR.iterdir()):
        if not mdir.is_dir():
            continue
        idx_path = mdir / "_index.json"
        if not idx_path.exists():
            continue
        kernels = _mission_kernels(mdir)
        if not kernels:
            continue
        idx = json.loads(idx_path.read_text())
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


def write_probes(
    session: Session,
    download_dir: Path,
    out_dir: Path,
    has_localized: dict[str, bool],
) -> dict[str, dict]:
    """Build per-zone, per-chunk binary files for every probe on disk.

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

    # First pass: build per-(zone, chunk_idx) lists of (probe_id, [SubChunkFit]).
    # Furnish generic kernels once at the outer level; per-probe mission
    # kernels are furnished/unfurnished inside the probe loop.
    n_generic = _furnish_generic_kernels(download_dir / PROVIDERS.SPICE / "kernels")
    logger.info("Probes export: furnished %d generic kernels", n_generic)
    probes = _enumerate_probes()
    logger.info("Probes export: %d spacecraft to process", len(probes))

    # zone_key → chunk_idx → list[(probe_id, first_subchunk_offset, [SubChunkFit])]
    by_zone_chunk: dict[str, dict[int, list[tuple[int, int, list[SubChunkFit]]]]] = (
        defaultdict(lambda: defaultdict(list))
    )

    try:
        for i, (mdir, kernels, naif_id) in enumerate(probes, 1):
            kpaths = [str(k) for k in kernels]
            for k in kernels:
                spiceypy.furnsh(str(k))
            try:
                landed, body = is_landed_probe(naif_id, kpaths)
                if landed:
                    logger.info(
                        "[%d/%d] [skipped] %s naif=%d landed on body %s",
                        i,
                        len(probes),
                        mdir.name,
                        naif_id,
                        body,
                    )
                    continue

                # Pin probe_id (uses the on-disk cache; same as ingestor).
                cov = _coverage(naif_id, kpaths)
                if cov is None:
                    logger.warning("no coverage for %s/%d", mdir.name, naif_id)
                    continue
                rec = assign(
                    mission=mdir.name,
                    naif_id=naif_id,
                    inception_mjd=et_to_mjd(cov[0]),
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

                intervals = classify_trace(naif_id, kpaths)
                logger.info(
                    "[%d/%d] %s naif=%d probe_id=%d (%d zone intervals)",
                    i,
                    len(probes),
                    mdir.name,
                    naif_id,
                    probe_id,
                    len(intervals),
                )
                for iv in intervals:
                    zone = ZONES_BY_KEY[iv.zone_key]
                    sub_s = zone.kepler_subchunk_days * _S_PER_DAY
                    for chunk_idx, c_start, c_end in _chunk_aligned_range(
                        zone.chunk_years,
                        zone.kepler_subchunk_days,
                        iv.start_et,
                        iv.end_et,
                        start_jd,
                    ):
                        chunk_sizing = size_chunk(naif_id, zone, c_start, c_end)
                        if not chunk_sizing.sub_chunks:
                            continue
                        chunk_start_et = (
                            _jd_to_et(start_jd)
                            + chunk_idx * zone.chunk_years * 365.25 * _S_PER_DAY
                        )
                        # Each chunk's first sub-chunk offset (relative to chunk
                        # start, in subchunk_days units) lets the frontend
                        # locate sub-chunk t-bounds without storing them.
                        first_offset = int(
                            round(
                                (chunk_sizing.sub_chunks[0].t_start_et - chunk_start_et)
                                / sub_s
                            )
                        )
                        by_zone_chunk[iv.zone_key][chunk_idx].append(
                            (probe_id, first_offset, list(chunk_sizing.sub_chunks))
                        )
            finally:
                for k in kernels:
                    spiceypy.unload(str(k))
    finally:
        spiceypy.kclear()

    # Second pass: serialize each (zone, chunk_idx) into a .bin.gz file.
    probes_dir = out_dir / "position" / "probes"
    manifest: dict[str, dict] = {}
    for zone in ALL_ZONES:
        zone_chunks = by_zone_chunk.get(zone.key)
        if not zone_chunks:
            continue
        zone_out = probes_dir / zone.key
        zone_out.mkdir(parents=True, exist_ok=True)

        total_bytes = 0
        n_chunks = 0
        for chunk_idx, probe_records in sorted(zone_chunks.items()):
            # Deterministic body order: ascending probe_id.
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

            data = b"".join(buf)
            with gzip.open(zone_out / f"{chunk_idx}.bin.gz", "wb") as f:
                f.write(data)
            total_bytes += len(data)
            n_chunks += 1

        # Chunk count in manifest is the *total* expected chunks across the
        # global time window — frontend computes chunk index from any JD via
        # `floor((jd - start_jd) / chunk_years / 365.25)`. Same convention
        # as chebyshev export.
        total_window_chunks = max(
            1, math.ceil((end_jd - start_jd) / (zone.chunk_years * 365.25))
        )
        avg_kb = (total_bytes // n_chunks) // 1024 if n_chunks else 0
        logger.info(
            "  probes/%s: %d emitted chunks (of %d window), avg %d KB/chunk, %.1f MB",
            zone.key,
            n_chunks,
            total_window_chunks,
            avg_kb,
            total_bytes / 1024 / 1024,
        )
        manifest[f"probes/{zone.key}"] = {
            "chunks": total_window_chunks,
            "chunk_years": zone.chunk_years,
            "start_jd": start_jd,
            "end_jd": end_jd,
            "subchunk_days": zone.kepler_subchunk_days,
            "float64_coeffs": zone.float64_coeffs,
        }

    return manifest
