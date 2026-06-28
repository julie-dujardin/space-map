"""Export Chebyshev polynomial ephemeris as chunked position files.

Reads per-body `.npz` files produced by the SPICE download step and emits one
gzipped position file per (zone, time-chunk) at `position/{zone}/{chunk}.bin.gz`
(the multi-zoom `major` zone keeps a `/0/` segment). The binary's per-body
header carries `id_type` + `obj_id_value` so the frontend can rebuild the full
`<prefix>-<numeric>` Object ID — Pluto and the perturber asteroids ride as
`spkid-…` even though their SPICE naif_id is the planetary ID.

The chebyshev payload always sits at zoom 0 — the most accurate tier for the
most important bodies.
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

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import (
    CHEBYSHEV_FLAG_FLOAT64_COEFFS,
    ID_TYPE_ORDINAL,
    MISSING_ID_TYPE,
    MISSING_INT32,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    pack_body_header,
    pack_chebyshev_header,
)
from space_map_data.export.position.layout import position_zone_dir
from space_map_data.export.position.origin import visible_from_days
from space_map_data.models.object import Object, ObjectType
from space_map_data.utils.naif import (
    CHEBYSHEV_ASTEROID_WHITELIST,
    CHEBYSHEV_PARENT_CHUNK_YEARS,
    spk_id_from_naif,
)

from space_map_data.utils.time import DAYS_PER_YEAR, year_to_jd

logger = logging.getLogger(__name__)

# Zone routing: core bodies + asteroids go to flat `major` / `major_asteroids`
# zones at a coarse chunk cadence (planets + sun barely move over years).
# Whitelisted moons get one `moons/<parent>` zone per parent at a per-parent
# chunk cadence (`CHEBYSHEV_PARENT_CHUNK_YEARS`).
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

# Zones where float32 coefficients lose visible precision because the body's
# absolute distance from its parent is large. The Sun-orbiter zones sit at
# ~1e9–6e9 km from SSB, which is right at float32's 7-digit limit and produces
# hundreds of km of quantization error. Moon zones are parent-relative and stay
# well below the float32 limit, so they keep the cheaper dtype.
_FLOAT64_ZONES = frozenset({"major", "major_asteroids"})


def _load_body_npz(
    path: Path,
) -> tuple[int, int, np.ndarray, np.ndarray, np.ndarray]:
    """Load one per-body .npz. Returns (naif_id, parent_id, start_jds, end_jds, coeffs)."""
    data = np.load(path)
    meta = data["meta"]
    naif_id = int(meta[0])
    parent_id = int(meta[1])
    return (
        naif_id,
        parent_id,
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


def should_export(obj: Object, naif_id: int) -> bool:
    """Defense-in-depth gate against stale `.npz` files in the cheb dir.

    The download-time `_should_extract` (download/.../chebyshev.py) is the
    primary filter — it controls which bodies get sampled in the first place
    — but stale files from before a whitelist tightening can linger in the
    cheb dir until the next download run cleans them up. Mirroring the
    asteroid whitelist here means the export reflects the current whitelist
    constant immediately, regardless of download dir state.
    """
    if (
        obj.object_type in _ASTEROID_TYPES
        and naif_id not in CHEBYSHEV_ASTEROID_WHITELIST
    ):
        return False
    return True


def _slice_segments(
    start_jds: np.ndarray,
    end_jds: np.ndarray,
    coeffs: np.ndarray,
    chunk_start_jd: float,
    chunk_end_jd: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the subset of segments overlapping [chunk_start, chunk_end)."""
    mask = (end_jds > chunk_start_jd) & (start_jds < chunk_end_jd)
    return start_jds[mask], end_jds[mask], coeffs[mask]


def _determine_zone(object_type: ObjectType, naif_id: int, parent_id: int) -> str:
    """Route a body to its zone path. Moons go to `moons/<parent>`."""
    if object_type in _ASTEROID_TYPES:
        return "major_asteroids"
    if object_type == ObjectType.moon:
        parent_name = _PARENT_NAMES.get(parent_id, f"other-{parent_id}")
        return f"moons/{parent_name}"
    return "major"


def _moon_parent_id(zone: str) -> int | None:
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
    files aggregate many bodies and one bad ID shouldn't take down the export.
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
    bodies: list[
        tuple[Object, int, int, np.ndarray, np.ndarray, np.ndarray, float, bool]
    ],
    float64_coeffs: bool,
) -> int:
    """Write one chunk file at `position/{zone}[/0]/{chunk_idx}.bin.gz` — the
    zoom segment only for the multi-zoom ``major`` zone.

    Returns bytes written for the bin file.
    """
    chunk_dir = position_zone_dir(out_dir, zone, 0)
    chunk_dir.mkdir(parents=True, exist_ok=True)

    coeff_dtype = np.float64 if float64_coeffs else np.float32
    flags = CHEBYSHEV_FLAG_FLOAT64_COEFFS if float64_coeffs else 0
    buf: list[bytes] = []
    buf.append(
        pack_chebyshev_header(chunk_start_jd, chunk_end_jd, len(bodies), flags=flags)
    )

    for (
        obj,
        naif_id,
        parent_id,
        seg_starts,
        seg_ends,
        seg_coeffs,
        radius_km,
        has_loc,
    ) in bodies:
        id_type, obj_id_value = _obj_id_parts(obj)
        n_segments = seg_starts.shape[0]
        coeffs_per_axis = seg_coeffs.shape[2] if n_segments > 0 else 0
        buf.append(
            pack_body_header(
                naif_id=naif_id,
                parent_id=parent_id,
                obj_id_value=obj_id_value,
                radius_km=float(radius_km) if radius_km is not None else float("nan"),
                coeffs_per_axis=coeffs_per_axis,
                id_type_ordinal=id_type,
                has_localized=has_loc,
                object_type_ordinal=OBJECT_TYPE_ORDINAL.get(
                    obj.object_type, MISSING_UINT8
                ),
                segment_count=n_segments,
                # Per-chunk start: a moon discovered before this chunk opens is
                # always visible within it (NaN), so the gate only bites the
                # chunk straddling its discovery and the ones before.
                visible_from_days=visible_from_days(obj, chunk_start_jd),
            )
        )
        if n_segments == 0:
            continue
        starts_f64 = np.ascontiguousarray(seg_starts, dtype=np.float64)
        ends_f64 = np.ascontiguousarray(seg_ends, dtype=np.float64)
        coeffs_packed = np.ascontiguousarray(seg_coeffs, dtype=coeff_dtype)
        for i in range(n_segments):
            buf.append(struct.pack("<dd", float(starts_f64[i]), float(ends_f64[i])))
            buf.append(coeffs_packed[i].tobytes(order="C"))

    data = b"".join(buf)
    out_path = chunk_dir / f"{chunk_idx}.bin.gz"
    with gzip.open(out_path, "wb") as f:
        f.write(data)

    return len(data)


def write_chebyshev(
    session: Session,
    download_dir: Path,
    out_dir: Path,
    radii: dict[int, dict],
    has_localized: dict[str, bool],
) -> dict[str, dict]:
    """Write Chebyshev exports. Returns a per-zone manifest fragment.

    Reads per-body .npz files in `download_dir/spice/chebyshev/`, links each to
    its DB Object, partitions by zone (major / major_asteroids / moons/<parent>)
    and time chunk, and emits one position file per (zone, chunk_idx) at zoom 0.
    The full Object ID (e.g. `naif-499`, `spkid-20134340`) is encoded inside
    the binary's per-body header. `has_localized` (built once during the export
    pass, keyed by Object.id) drops one bit per body into the body header so
    the frontend can skip detail-bundle fetches for objects with no Wikidata.

    Chunk parameters come from the SPICE download metadata so the export
    matches exactly what was extracted.

    Returns a dict mapping zone → `{chunks, chunk_days, start_jd, end_jd}`.
    The caller folds these per-zone into the unified position manifest with
    `shape="chunked"`. Returns `{}` when there's nothing to export.
    """
    cheb_dir = download_dir / "derived" / "position" / "chebyshev"
    if not cheb_dir.exists():
        logger.info("No Chebyshev data in %s, skipping", cheb_dir)
        return {}

    meta_path = download_dir / "derived" / "position" / "tables" / "metadata.json"
    if not meta_path.exists():
        logger.warning(
            "SPICE metadata missing at %s, skipping Chebyshev export", meta_path
        )
        return {}
    meta = orjson.loads(meta_path.read_bytes())
    start_year = int(meta.get("chebyshev_start_year", 1950))
    end_year = int(meta.get("chebyshev_end_year", 2050))
    core_chunk_years = float(meta.get("chebyshev_chunk_years", 5))
    start_jd_total = year_to_jd(start_year)
    end_jd_total = year_to_jd(end_year)
    logger.info(
        "Exporting Chebyshev: %d→%d (core %.1fy chunks; moons per-parent)",
        start_year,
        end_year,
        core_chunk_years,
    )

    # Group bodies by zone and retain everything in memory (small — ≤80 bodies
    # across the whole export after filtering).
    zone_bodies: dict[str, list] = defaultdict(list)
    skipped_filter = 0
    for path in sorted(cheb_dir.glob("*.npz")):
        naif_id, parent_id, start_jds, end_jds, coeffs = _load_body_npz(path)
        obj = _object_for_naif_id(session, naif_id)
        if obj is None:
            logger.warning(
                "Chebyshev: no DB object for naif_id=%d (file=%s); skipping",
                naif_id,
                path.name,
            )
            continue
        if not should_export(obj, naif_id):
            skipped_filter += 1
            continue
        radius = (radii.get(naif_id) or {}).get("a")
        zone = _determine_zone(obj.object_type, naif_id, parent_id)
        has_loc = bool(has_localized.get(obj.id, False))
        zone_bodies[zone].append(
            (obj, naif_id, parent_id, start_jds, end_jds, coeffs, radius, has_loc)
        )
    if skipped_filter:
        logger.info(
            "Chebyshev: skipped %d body file(s) outside the active whitelist "
            "(stale `.npz`s from a previous download — next download run will "
            "remove them)",
            skipped_filter,
        )

    zone_manifest: dict[str, dict] = {}
    for zone, bodies in zone_bodies.items():
        # Deterministic body order inside each zone — stable by NAIF ID so
        # consumers don't have to sort.
        bodies.sort(key=lambda row: row[1])
        is_moon_tier = zone.startswith("moons/")
        if is_moon_tier:
            parent_id = _moon_parent_id(zone)
            chunk_years = CHEBYSHEV_PARENT_CHUNK_YEARS.get(parent_id or 0, 0.5)
        else:
            chunk_years = core_chunk_years
        chunk_days = chunk_years * DAYS_PER_YEAR
        float64_coeffs = zone in _FLOAT64_ZONES
        n_chunks = max(1, math.ceil((end_year - start_year) / chunk_years))
        total_bytes = 0
        for chunk_idx in range(n_chunks):
            chunk_start_jd = start_jd_total + chunk_idx * chunk_days
            chunk_end_jd = chunk_start_jd + chunk_days
            if chunk_idx == n_chunks - 1:
                chunk_end_jd = end_jd_total  # absorb rounding at the tail
            chunk_bodies: list = []
            for (
                obj,
                naif_id,
                parent_id,
                start_jds,
                end_jds,
                coeffs,
                radius,
                has_loc,
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
                        parent_id,
                        seg_starts,
                        seg_ends,
                        seg_coeffs,
                        radius,
                        has_loc,
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
                float64_coeffs,
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
        zone_manifest[zone] = {
            "chunks": n_chunks,
            "chunk_days": chunk_days,
            "start_jd": start_jd_total,
            "end_jd": end_jd_total,
            "float64_coeffs": float64_coeffs,
        }

    return zone_manifest
