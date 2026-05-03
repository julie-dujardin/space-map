"""Export Chebyshev polynomial ephemeris as chunked binary files.

Reads per-body `.npz` files produced by the SPICE download step and emits one
(gzipped) binary per (zone, time-chunk) under `chebyshev/{zone}/{chunk}/`. The
binary's per-body header carries `id_type` + `obj_id_value` so the frontend can
rebuild the full `<prefix>-<numeric>` Object ID — Pluto and the perturber
asteroids ride as `spkid-…` even though their SPICE naif_id is the planetary
ID.
"""

import gzip
import logging
import math
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np
import orjson
from sqlalchemy.orm import Session

from space_map_data.constants.providers import ID_TYPES, PROVIDERS
from space_map_data.export.chebyshev.format import (
    ID_TYPE_ORDINAL,
    MISSING_ID_TYPE,
    pack_body_header,
    pack_header,
)
from space_map_data.export.elements.format import MISSING_INT32
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.naif import (
    CHEBYSHEV_PARENT_CHUNK_YEARS,
    spk_id_from_naif,
)

logger = logging.getLogger(__name__)

_S_PER_DAY = 86400.0
_J2000_JD = 2451545.0

# Zone routing: core bodies + asteroids go to flat `major` / `major_asteroids`
# zones at a coarse chunk cadence (planets + sun barely move over years).
# Whitelisted moons get one `moons/<parent>` zone per parent at a per-parent
# chunk cadence (`CHEBYSHEV_PARENT_CHUNK_YEARS`). The previous inner/main split
# was dropped — chunks are now uniformly ~200 KB regardless of body density,
# achieved by varying chunk_years per parent rather than per-body bucket.
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
_PARENT_NAMES = {
    1: "mercury",
    2: "venus",
    3: "earth",
    4: "mars",
    5: "jupiter",
    6: "saturn",
    7: "uranus",
    8: "neptune",
    9: "pluto",
}


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


def _determine_zone(object_type: ObjectType, naif_id: int, parent_naif_id: int) -> str:
    """Route a body to its zone path. Moons go to `moons/<parent>`."""
    if object_type in _ASTEROID_TYPES:
        return "major_asteroids"
    if object_type == ObjectType.moon:
        parent_name = _PARENT_NAMES.get(parent_naif_id, f"other-{parent_naif_id}")
        return f"moons/{parent_name}"
    return "major"


def _moon_parent_naif_id(zone: str) -> int | None:
    """Reverse `moons/<parent>` zone path → parent NAIF ID for chunk-cadence lookup."""
    if not zone.startswith("moons/"):
        return None
    name = zone.split("/", 1)[1]
    for naif_id, parent_name in _PARENT_NAMES.items():
        if parent_name == name:
            return naif_id
    return None


def _obj_id_parts(obj: Object) -> tuple[int, int]:
    """Return `(id_type_ordinal, obj_id_value)` for one chebyshev body.

    Pulled from `Object.id` (`<prefix>-<numeric>`) rather than the SPICE naif_id
    so Pluto/perturber-asteroid bodies retain their `spkid-…` form across the
    binary. Logs and falls back to sentinels rather than raising — chebyshev
    chunks aggregate many bodies and one bad ID shouldn't take down the export.
    """
    pos = obj.id.find("-")
    if pos == -1:
        logger.warning("chebyshev: %s has no separator in object ID", obj.id)
        return MISSING_ID_TYPE, MISSING_INT32
    prefix, value = obj.id[:pos], obj.id[pos + 1 :]
    try:
        ordinal = ID_TYPE_ORDINAL[ID_TYPES(prefix)]
    except (KeyError, ValueError):
        logger.warning("chebyshev: %s has unsupported id type %r", obj.id, prefix)
        return MISSING_ID_TYPE, MISSING_INT32
    try:
        return ordinal, int(value)
    except ValueError:
        logger.warning("chebyshev: %s has non-integer id value %r", obj.id, value)
        return ordinal, MISSING_INT32


def _write_chunk_file(
    out_dir: Path,
    zone: str,
    chunk_idx: int,
    chunk_start_jd: float,
    chunk_end_jd: float,
    bodies: list[tuple[Object, int, int, np.ndarray, np.ndarray, np.ndarray, float]],
) -> int:
    """Write one chunk file. Returns bytes written for the bin file."""
    chunk_dir = out_dir / "chebyshev" / zone / str(chunk_idx)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    buf: list[bytes] = []
    buf.append(pack_header(chunk_start_jd, chunk_end_jd, len(bodies)))

    for (
        obj,
        naif_id,
        parent_naif_id,
        seg_starts,
        seg_ends,
        seg_coeffs,
        radius_km,
    ) in bodies:
        id_type, obj_id_value = _obj_id_parts(obj)
        n_segments = seg_starts.shape[0]
        coeffs_per_axis = seg_coeffs.shape[2] if n_segments > 0 else 0
        buf.append(
            pack_body_header(
                naif_id=naif_id,
                parent_naif_id=parent_naif_id,
                obj_id_value=obj_id_value,
                radius_km=float(radius_km) if radius_km is not None else float("nan"),
                coeffs_per_axis=coeffs_per_axis,
                id_type_ordinal=id_type,
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
    and emits one binary file per (zone, chunk). The full Object ID (e.g.
    `naif-499`, `spkid-20134340`) is encoded inside the binary's per-body
    header — no sidecar id file is emitted.

    Chunk parameters come from the SPICE download metadata so the export
    matches exactly what was extracted.

    The manifest collapses zones into two tiers — `sun` (slow movers, coarse
    chunks) and `moons` (fast movers, fine chunks) — sharing JD bounds at the
    top level. Tier params are uniform across all zones in that tier.
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
    core_chunk_years = float(meta.get("chebyshev_chunk_years", 5))
    start_jd_total = _year_to_jd(start_year)
    end_jd_total = _year_to_jd(end_year)
    logger.info(
        "Exporting Chebyshev: %d→%d (core %.1fy chunks; moons per-parent)",
        start_year,
        end_year,
        core_chunk_years,
    )

    # Group bodies by zone and retain everything in memory (small — ≤80 bodies
    # across the whole export after filtering).
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
        zone = _determine_zone(obj.object_type, naif_id, parent_naif_id)
        zone_bodies[zone].append(
            (obj, naif_id, parent_naif_id, start_jds, end_jds, coeffs, radius)
        )

    sun_zones: list[str] = []
    moon_zone_entries: list[dict] = []
    sun_chunks = max(1, math.ceil((end_year - start_year) / core_chunk_years))
    for zone, bodies in zone_bodies.items():
        # Deterministic body order inside each zone — stable by NAIF ID so
        # consumers don't have to sort.
        bodies.sort(key=lambda row: row[1])
        is_moon_tier = zone.startswith("moons/")
        if is_moon_tier:
            parent_id = _moon_parent_naif_id(zone)
            chunk_years = CHEBYSHEV_PARENT_CHUNK_YEARS.get(parent_id or 0, 0.5)
        else:
            chunk_years = core_chunk_years
        n_chunks = max(1, math.ceil((end_year - start_year) / chunk_years))
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
        avg_kb = (total_bytes // n_chunks) // 1024 if n_chunks else 0
        logger.info(
            "  %s: %d bodies, %d chunks (%.3fy each), avg %d KB/chunk, %.1f MB total",
            zone,
            len(bodies),
            n_chunks,
            chunk_years,
            avg_kb,
            total_bytes / 1024 / 1024,
        )
        if is_moon_tier:
            moon_zone_entries.append(
                {"zone": zone, "chunks": n_chunks, "chunk_years": chunk_years}
            )
        else:
            sun_zones.append(zone)

    sun_zones.sort()
    moon_zone_entries.sort(key=lambda e: e["zone"])
    return {
        "start_jd": start_jd_total,
        "end_jd": end_jd_total,
        "sun": {
            "chunks": sun_chunks,
            "chunk_years": core_chunk_years,
            "zones": sun_zones,
        },
        "moons": {
            # Each zone carries its own (chunks, chunk_years) — Saturn ships
            # 0.125y chunks while Pluto ships 2y, etc. Frontend indexes per-zone:
            # `chunk_idx = floor((jd - start_jd) / (chunk_years * 365.25))`.
            "zones": moon_zone_entries,
        },
    }
