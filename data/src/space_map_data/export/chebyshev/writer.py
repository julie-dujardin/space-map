"""Export Chebyshev polynomial ephemeris as chunked binary files.

Reads per-body `.npz` files produced by the SPICE download step and emits one
(gzipped) binary per (zone, time-chunk) under `chebyshev/{zone}/{chunk}/`. A
sidecar `data.id.gz` lists the full `<source>-<numeric>` object IDs in the same
order as the binary body table, matching the elements-export convention.
"""

import gzip
import logging
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np
import orjson
from sqlalchemy.orm import Session

from space_map_data.constants.providers import PROVIDERS
from space_map_data.export.chebyshev.format import (
    VERSION,
    pack_body_header,
    pack_header,
)
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.naif import spk_id_from_naif

logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0

# Zone routing mirrors the elements export (`major` / `moons` / zone-per-class
# for small bodies) so clients already subscribed to a zone's elements file
# naturally discover the matching Chebyshev file. Moons live in their own zone
# because they dominate payload size — a client that doesn't need sub-system
# precision can skip them entirely.
_ASTEROID_TYPES = frozenset(
    {
        ObjectType.asteroid,
        ObjectType.asteroid_inner,
        ObjectType.asteroid_main_belt,
        ObjectType.asteroid_trojan,
        ObjectType.asteroid_centaur,
        ObjectType.asteroid_tno,
    }
)


def _year_to_jd(year: int) -> float:
    """Civil year start (Jan 1) → Julian Date TDB (approximate, good to seconds)."""
    # Gregorian → JD at 00:00 UT, Jan 1 of `year`.
    # Good enough for chunk bounds; we're not doing sub-second work here.
    import datetime

    d = datetime.date(year, 1, 1)
    return d.toordinal() + 1721424.5


def _load_body_npz(
    path: Path,
) -> tuple[int, int, np.ndarray, np.ndarray, np.ndarray]:
    """Load one per-body .npz. Returns (naif_id, parent_naif_id, start_jds, end_jds, coeffs)."""
    data = np.load(path)
    meta = data["meta"]
    naif_id = int(meta[0])
    parent_naif_id = int(meta[1])
    return (
        naif_id,
        parent_naif_id,
        data["start_jds"],
        data["end_jds"],
        data["coeffs"],
    )


def _object_for_naif_id(session: Session, naif_id: int) -> Object | None:
    """Find an Object row by NAIF ID, falling back to SBDB SPK-ID mapping."""
    obj = session.query(Object).filter(Object.naif_id == naif_id).one_or_none()
    if obj is not None:
        return obj
    fallback_spkid = spk_id_from_naif(naif_id)
    if fallback_spkid is not None:
        return (
            session.query(Object).filter(Object.spkid == fallback_spkid).one_or_none()
        )
    return None


def _slice_segments(
    start_jds: np.ndarray,
    end_jds: np.ndarray,
    coeffs: np.ndarray,
    chunk_start_jd: float,
    chunk_end_jd: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the subset of segments overlapping [chunk_start, chunk_end)."""
    # Overlap condition: seg.end > chunk_start AND seg.start < chunk_end
    mask = (end_jds > chunk_start_jd) & (start_jds < chunk_end_jd)
    return start_jds[mask], end_jds[mask], coeffs[mask]


def _determine_zone(object_type: ObjectType) -> str:
    if object_type in _ASTEROID_TYPES:
        return "major_asteroids"
    if object_type == ObjectType.moon:
        return "moons"
    return "major"


def _write_chunk_file(
    out_dir: Path,
    zone: str,
    chunk_idx: int,
    chunk_start_jd: float,
    chunk_end_jd: float,
    bodies: list[tuple[Object, int, int, np.ndarray, np.ndarray, np.ndarray, float]],
) -> int:
    """Write one chunk file + sidecar id file. Returns bytes written for the bin file."""
    chunk_dir = out_dir / "chebyshev" / zone / str(chunk_idx)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    buf: list[bytes] = []
    buf.append(pack_header(chunk_start_jd, chunk_end_jd, len(bodies)))

    ids_text: list[str] = []
    for (
        obj,
        naif_id,
        parent_naif_id,
        seg_starts,
        seg_ends,
        seg_coeffs,
        radius_km,
    ) in bodies:
        ids_text.append(obj.id)
        n_segments = seg_starts.shape[0]
        coeffs_per_axis = seg_coeffs.shape[2] if n_segments > 0 else 0
        buf.append(
            pack_body_header(
                naif_id=naif_id,
                parent_naif_id=parent_naif_id,
                radius_km=float(radius_km) if radius_km is not None else float("nan"),
                coeffs_per_axis=coeffs_per_axis,
                segment_count=n_segments,
            )
        )
        # Segment bodies: (start_jd, end_jd, x-coeffs, y-coeffs, z-coeffs) packed per segment.
        # Float64 bounds then contiguous float32 coefficient triples.
        if n_segments == 0:
            continue
        starts_f64 = np.ascontiguousarray(seg_starts, dtype=np.float64)
        ends_f64 = np.ascontiguousarray(seg_ends, dtype=np.float64)
        coeffs_f32 = np.ascontiguousarray(seg_coeffs, dtype=np.float32)
        # Interleave per segment: we want [start, end, cx[0..N], cy[0..N], cz[0..N]] × segments
        # rather than separate arrays, so consumers can scan sequentially.
        for i in range(n_segments):
            buf.append(struct.pack("<dd", float(starts_f64[i]), float(ends_f64[i])))
            buf.append(coeffs_f32[i].tobytes(order="C"))

    data = b"".join(buf)
    out_path = chunk_dir / "data.bin.gz"
    with gzip.open(out_path, "wb") as f:
        f.write(data)

    id_path = chunk_dir / "data.id.gz"
    with gzip.open(id_path, "wb") as f:
        f.write("\n".join(ids_text).encode("utf-8"))

    return len(data)


def write_chebyshev(
    session: Session,
    download_dir: Path,
    out_dir: Path,
    radii: dict[int, dict],
) -> dict:
    """Write Chebyshev exports. Returns manifest entry for metadata.json.

    Reads per-body .npz files in `download_dir/spice/chebyshev/`, links each to
    its DB Object, partitions by zone (major / major_asteroids) and time chunk,
    and emits one binary + sidecar id file per (zone, chunk).

    Chunk parameters come from the SPICE download metadata so the export
    matches exactly what was extracted.
    """
    cheb_dir = download_dir / PROVIDERS.SPICE / "chebyshev"
    if not cheb_dir.exists():
        logger.info("No Chebyshev data in %s, skipping", cheb_dir)
        return {}

    meta_path = download_dir / PROVIDERS.SPICE / "metadata.json"
    if not meta_path.exists():
        logger.warning(
            "SPICE metadata missing at %s, skipping Chebyshev export", meta_path
        )
        return {}
    meta = orjson.loads(meta_path.read_bytes())
    start_year = int(meta.get("chebyshev_start_year", 1950))
    end_year = int(meta.get("chebyshev_end_year", 2050))
    chunk_years = int(meta.get("chebyshev_chunk_years", 10))
    start_jd_total = _year_to_jd(start_year)
    end_jd_total = _year_to_jd(end_year)
    n_chunks = (end_year - start_year + chunk_years - 1) // chunk_years
    logger.info(
        "Exporting Chebyshev: %d→%d in %d-year chunks (%d chunks total)",
        start_year,
        end_year,
        chunk_years,
        n_chunks,
    )

    # Group bodies by zone and retain everything in memory (data is modest —
    # ≤50 bodies in major, ≤16 in major_asteroids).
    zone_bodies: dict[str, list] = defaultdict(list)
    for path in sorted(cheb_dir.glob("*.npz")):
        naif_id, parent_naif_id, start_jds, end_jds, coeffs = _load_body_npz(path)
        obj = _object_for_naif_id(session, naif_id)
        if obj is None:
            logger.warning(
                "Chebyshev: no DB object for naif_id=%d (file=%s); skipping",
                naif_id,
                path.name,
            )
            continue
        radius = (radii.get(naif_id) or {}).get("a")
        zone = _determine_zone(obj.object_type)
        zone_bodies[zone].append(
            (obj, naif_id, parent_naif_id, start_jds, end_jds, coeffs, radius)
        )

    manifest_zones: dict[str, dict] = {}
    for zone, bodies in zone_bodies.items():
        # Deterministic body order inside each zone — stable by NAIF ID so
        # consumers don't have to sort.
        bodies.sort(key=lambda row: row[1])
        total_bytes = 0
        for chunk_idx in range(n_chunks):
            chunk_start_jd = start_jd_total + chunk_idx * chunk_years * 365.25
            chunk_end_jd = chunk_start_jd + chunk_years * 365.25
            if chunk_idx == n_chunks - 1:
                chunk_end_jd = end_jd_total  # absorb rounding at the tail
            chunk_bodies: list = []
            for (
                obj,
                naif_id,
                parent_naif_id,
                start_jds,
                end_jds,
                coeffs,
                radius,
            ) in bodies:
                seg_starts, seg_ends, seg_coeffs = _slice_segments(
                    start_jds, end_jds, coeffs, chunk_start_jd, chunk_end_jd
                )
                if seg_starts.size == 0:
                    continue
                chunk_bodies.append(
                    (
                        obj,
                        naif_id,
                        parent_naif_id,
                        seg_starts,
                        seg_ends,
                        seg_coeffs,
                        radius,
                    )
                )
            if not chunk_bodies:
                continue
            nbytes = _write_chunk_file(
                out_dir,
                zone,
                chunk_idx,
                chunk_start_jd,
                chunk_end_jd,
                chunk_bodies,
            )
            total_bytes += nbytes
            logger.info(
                "  %s chunk %d: %d bodies, %d KB",
                zone,
                chunk_idx,
                len(chunk_bodies),
                nbytes // 1024,
            )
        manifest_zones[zone] = {
            "chunks": n_chunks,
            "start_jd": start_jd_total,
            "end_jd": end_jd_total,
            "chunk_years": chunk_years,
            "body_count": len(bodies),
            "total_bytes": total_bytes,
        }

    return {
        "version": VERSION,
        "zones": manifest_zones,
    }
