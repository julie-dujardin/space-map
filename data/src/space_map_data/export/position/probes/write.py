"""Pass 3 of the probes exporter: pack fits to bytes, atomic-write per
chunk, build the position manifest entries.

Owns the wire-format adapters (`_pack_kepler_payload`, `_pack_subchunk`,
`_pack_landed_subchunk`) since they're only consumed here, plus the
multi-interval grid padding and the per-zone manifest assembly.
"""

import gzip
import logging
import math
from pathlib import Path

import numpy as np

from space_map_data.export.position.format import (
    METHOD_CHEBYSHEV,
    METHOD_KEPLER_DRIFT,
    METHOD_KEPLER_PURE,
    METHOD_LANDED,
    METHOD_UNCOVERABLE,
    pack_landed_payload,
    pack_probe_header,
    pack_probes_header,
    pack_subchunk_record,
    pack_system_interval,
)
from space_map_data.export.position.probes import sidecar
from space_map_data.export.position.probes.landed import LandedFit
from space_map_data.export.position.probes.plan import (
    ChunkProbeRecord,
    ProbeMeta,
    ProbePlan,
)
from space_map_data.export.position.probes.sizing import (
    METHOD_CHEBYSHEV as SZ_METHOD_CHEBYSHEV,
    METHOD_KEPLER_DRIFT as SZ_METHOD_KEPLER_DRIFT,
    METHOD_KEPLER_PURE as SZ_METHOD_KEPLER_PURE,
    METHOD_UNCOVERABLE as SZ_METHOD_UNCOVERABLE,
    SubChunkFit,
)
from space_map_data.export.position.probes.time_grid import S_PER_DAY, jd_to_et
from space_map_data.probes.zones import ALL_ZONES, Zone

logger = logging.getLogger(__name__)


_METHOD_ORDINAL = {
    SZ_METHOD_KEPLER_PURE: METHOD_KEPLER_PURE,
    SZ_METHOD_KEPLER_DRIFT: METHOD_KEPLER_DRIFT,
    SZ_METHOD_CHEBYSHEV: METHOD_CHEBYSHEV,
    SZ_METHOD_UNCOVERABLE: METHOD_UNCOVERABLE,
}


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


def _pack_landed_subchunk(fit: LandedFit) -> bytes:
    payload = pack_landed_payload(
        body_naif_id=fit.body_naif_id,
        is_static=fit.is_static,
        start_offset_s=fit.start_offset_s,
        end_offset_s=fit.end_offset_s,
        lat_ref_deg=fit.lat_ref_deg,
        lng_ref_deg=fit.lng_ref_deg,
        alt_ref_m=fit.alt_ref_m,
        samples=fit.samples,
    )
    return pack_subchunk_record(METHOD_LANDED, payload)


def _pad_flying_grid(
    flying: list[SubChunkFit],
    chunk_start_et: float,
    sub_s: float,
) -> tuple[int, list[SubChunkFit]] | None:
    """Sort `flying` by ET and insert `METHOD_UNCOVERABLE` records into
    grid gaps so the binary packs as a contiguous run on the sub-chunk
    grid. Required for probes whose multiple disjoint SPK intervals
    contribute to the same chunk — without padding the second interval's
    sub-chunks decode at off-by-one grid positions and break the Kepler
    anchor offset. Returns `(first_offset, padded)` or None if empty."""
    if not flying:
        return None
    sorted_flying = sorted(flying, key=lambda f: f.t_start_et)
    first_offset = int(round((sorted_flying[0].t_start_et - chunk_start_et) / sub_s))
    expected_offset = first_offset
    padded: list[SubChunkFit] = []
    for f in sorted_flying:
        actual_offset = int(round((f.t_start_et - chunk_start_et) / sub_s))
        while expected_offset < actual_offset:
            slot_start_et = chunk_start_et + expected_offset * sub_s
            padded.append(
                SubChunkFit(
                    method=SZ_METHOD_UNCOVERABLE,
                    t_start_et=slot_start_et,
                    t_end_et=slot_start_et + sub_s,
                    bytes=0,
                    max_err_km=float("nan"),
                    detail="grid-gap pad (multi-interval probe coverage)",
                )
            )
            expected_offset += 1
        padded.append(f)
        expected_offset += 1
    return first_offset, padded


def _to_ranges(indices: list[int]) -> list[list[int]]:
    """Collapse a sorted list of unique ints into inclusive-inclusive ranges
    `[[start, end], ...]`. Lets the manifest declare every chunk index a probe
    file actually exists for without listing each one — dense zones collapse
    to a single range, sparse zones (Pluto, Uranus, …) to two or three."""
    if not indices:
        return []
    ranges: list[list[int]] = []
    start = prev = indices[0]
    for idx in indices[1:]:
        if idx == prev + 1:
            prev = idx
            continue
        ranges.append([start, prev])
        start = prev = idx
    ranges.append([start, prev])
    return ranges


def write_pass(
    chunk_index: dict[str, dict[int, list[ProbePlan]]],
    dirty: dict[str, dict[int, dict]],
    by_zone_chunk: dict[str, dict[int, list[ChunkProbeRecord]]],
    metas_by_probe_id: dict[int, ProbeMeta],
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

        # Sweep chunk files no probe contributes to anymore. Stale binaries
        # would otherwise show up in `present` and ship to the frontend.
        expected = set(all_chunks)
        n_stale = 0
        for stale in zone_out.glob("*.bin.gz"):
            try:
                idx = int(stale.name.split(".", 1)[0])
            except ValueError:
                continue
            if idx in expected:
                continue
            stale.unlink(missing_ok=True)
            sidecar.mirror_path(zone_out / f"{idx}.meta.json").unlink(missing_ok=True)
            n_stale += 1
        if n_stale:
            logger.info("  probes/%s: removed %d stale chunk(s)", zone_key, n_stale)

        n_emit = 0
        n_skip = 0
        total_bytes = 0
        for chunk_idx in sorted(all_chunks):
            binary_path = zone_out / f"{chunk_idx}.bin.gz"
            sidecar_path = sidecar.mirror_path(zone_out / f"{chunk_idx}.meta.json")

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

            probe_records.sort(key=lambda r: r.probe_id)
            chunk_start_jd = start_jd + chunk_idx * zone.chunk_years * 365.25
            chunk_end_jd = chunk_start_jd + zone.chunk_years * 365.25
            chunk_start_et = jd_to_et(chunk_start_jd)
            sub_s = zone.kepler_subchunk_days * S_PER_DAY

            buf: list[bytes] = [
                pack_probes_header(
                    start_jd=chunk_start_jd,
                    end_jd=chunk_end_jd,
                    probe_count=len(probe_records),
                    subchunk_days=zone.kepler_subchunk_days,
                )
            ]
            for rec in probe_records:
                meta = metas_by_probe_id[rec.probe_id]
                padded_flying = _pad_flying_grid(rec.flying, chunk_start_et, sub_s)
                rec.first_offset = (
                    padded_flying[0] if padded_flying else rec.first_offset
                )
                flying = padded_flying[1] if padded_flying else rec.flying
                buf.append(
                    pack_probe_header(
                        probe_id=meta.probe_id,
                        object_type_ordinal=meta.object_type_ordinal,
                        has_localized=meta.has_localized,
                        n_subchunks=len(flying),
                        first_subchunk_offset=rec.first_offset,
                        has_landed_record=rec.landed is not None,
                        fit_center_id_value=rec.fit_center_id_value,
                        fit_center_id_type=rec.fit_center_id_type,
                        n_system_intervals=len(rec.system_intervals),
                    )
                )
                for sc in flying:
                    buf.append(_pack_subchunk(sc, zone))
                if rec.landed is not None:
                    buf.append(_pack_landed_subchunk(rec.landed))
                for s_et, e_et, sys_naif in rec.system_intervals:
                    buf.append(pack_system_interval(s_et, e_et, sys_naif))
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
        present_indices = sorted(
            int(p.name.split(".", 1)[0]) for p in zone_out.glob("*.bin.gz")
        )
        manifest[f"probes/{zone_key}"] = {
            "chunks": total_window_chunks,
            "chunk_years": zone.chunk_years,
            "start_jd": start_jd,
            "end_jd": end_jd,
            "subchunk_days": zone.kepler_subchunk_days,
            "float64_coeffs": zone.float64_coeffs,
            "fit_center_naif_id": zone.fit_center_naif_id,
            "present": _to_ranges(present_indices),
        }

    return manifest
