"""Write the elements.bin.gz binary file (gzip-compressed)."""

import gzip
import io
import logging
import struct
from pathlib import Path

from space_map_data.export.elements.format import (
    FORMAT_PARABOLIC,
    FORMAT_SGP4,
    MISSING_FLOAT64,
    MISSING_INT32,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    SOURCE_ORDINAL,
    align8,
    pack_header,
)
from space_map_data.models.object import Object, OrbitalSource

logger = logging.getLogger(__name__)

_REQUIRED_KEPLERIAN = {"epoch_jd", "a", "e", "i", "om", "w", "ma", "n"}
_REQUIRED_SGP4 = ("BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")


def _source_ordinal(objects: list[Object], orbital_source: OrbitalSource) -> int:
    """Assert that every row's `orbital_source` matches (or is None) and return the ordinal.

    Enforces the one-provider-per-file invariant: if an object disagrees with
    the declared chunk source, export fails loud rather than writing a
    mis-attributed file.
    """
    for o in objects:
        if o.orbital_source is not None and o.orbital_source != orbital_source:
            raise ValueError(
                f"{o.id}: orbital_source {o.orbital_source!r} does not match "
                f"chunk source {orbital_source!r}"
            )
    return SOURCE_ORDINAL[orbital_source]


def _write_keplerian_columns(
    buf: io.BytesIO,
    objects: list[Object],
    radius_km_overrides: dict[str, float] | None,
) -> None:
    """Write columns 0–12 shared by the Keplerian and SGP4 formats."""
    n = len(objects)

    # Column 0: id (int32) — type-specific ID from Object.id
    _write_int32(buf, n, [_parse_numeric_id(o) for o in objects])

    # Column 1: object_type (uint8)
    _write_uint8(
        buf,
        n,
        [OBJECT_TYPE_ORDINAL.get(o.object_type, MISSING_UINT8) for o in objects],
    )

    # Column 2: parent_id (int32) — NAIF ID of parent body
    _write_int32(
        buf,
        n,
        [
            o.parent_naif_id if o.parent_naif_id is not None else MISSING_INT32
            for o in objects
        ],
    )

    # Column 3: scale (uint8)
    _write_uint8(
        buf,
        n,
        [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
    )

    # Column 4: epoch_jd (float64 — Julian Dates need full precision)
    _write_float64(buf, n, [_float_value(o, "epoch_jd") for o in objects])

    # Columns 5–11: float32 Keplerian orbital elements
    for attr in ("a", "e", "i", "om", "w", "ma", "n"):
        _write_float32(
            buf,
            n,
            [_float_value(o, attr) for o in objects],
        )

    # Column 12: radius_km (float32)
    _write_float32(buf, n, [_radius_km(o, radius_km_overrides) for o in objects])


def write_elements(
    objects: list[Object],
    out_file: Path,
    orbital_source: OrbitalSource,
    radius_km_overrides: dict[str, float] | None = None,
) -> None:
    """Write a Keplerian binary elements file (format_type=0).

    Raises ValueError if a required orbital element is None, or if any row's
    `orbital_source` disagrees with the chunk source.
    """
    n = len(objects)
    source = _source_ordinal(objects, orbital_source)
    buf = io.BytesIO()
    buf.write(pack_header(n, source_ordinal=source))
    _write_keplerian_columns(buf, objects, radius_km_overrides)
    out_file.write_bytes(gzip.compress(buf.getvalue()))


def write_sgp4_elements(
    objects: list[Object],
    out_file: Path,
    orbital_source: OrbitalSource,
    radius_km_overrides: dict[str, float] | None = None,
) -> None:
    """Write an SGP4 binary elements file (format_type=2).

    Columns 0–12 match the Keplerian layout; columns 13–17 carry the extra
    TLE/OMM fields needed by satellite.js `json2satrec`: BSTAR, MEAN_MOTION_DOT,
    MEAN_MOTION_DDOT (float32), ELEMENT_SET_NO, REV_AT_EPOCH (int32).

    Raises ValueError when a required SGP4 field is missing on any row, or if
    any row's `orbital_source` disagrees with the chunk source.
    """
    n = len(objects)
    source = _source_ordinal(objects, orbital_source)
    buf = io.BytesIO()
    buf.write(pack_header(n, FORMAT_SGP4, source_ordinal=source))
    _write_keplerian_columns(buf, objects, radius_km_overrides)

    # Columns 13–15: float32 SGP4 drag / rate fields from CelesTrak
    for attr in _REQUIRED_SGP4:
        _write_float32(buf, n, [_required_celestrak_float(o, attr) for o in objects])

    # Column 16: ELEMENT_SET_NO (int32, nullable)
    _write_int32(
        buf,
        n,
        [_celestrak_int(o, "ELEMENT_SET_NO") for o in objects],
    )

    # Column 17: REV_AT_EPOCH (int32, nullable)
    _write_int32(
        buf,
        n,
        [_celestrak_int(o, "REV_AT_EPOCH") for o in objects],
    )

    out_file.write_bytes(gzip.compress(buf.getvalue()))


def write_parabolic_elements(
    objects: list[Object],
    out_file: Path,
    orbital_source: OrbitalSource,
    radius_km_overrides: dict[str, float] | None = None,
) -> None:
    """Write a parabolic binary elements file (format_type=1).

    Columns: id, object_type, parent_id, scale, epoch_jd, q, e, i, om, w, tp, radius_km.
    Raises ValueError if a required element (q, tp, e, i, om, w) is missing, or
    if any row's `orbital_source` disagrees with the chunk source.
    """
    n = len(objects)
    source = _source_ordinal(objects, orbital_source)
    buf = io.BytesIO()

    buf.write(pack_header(n, FORMAT_PARABOLIC, source_ordinal=source))

    # Columns 0–3: same as Keplerian
    _write_int32(buf, n, [_parse_numeric_id(o) for o in objects])
    _write_uint8(
        buf,
        n,
        [OBJECT_TYPE_ORDINAL.get(o.object_type, MISSING_UINT8) for o in objects],
    )
    _write_int32(
        buf,
        n,
        [
            o.parent_naif_id if o.parent_naif_id is not None else MISSING_INT32
            for o in objects
        ],
    )
    _write_uint8(
        buf,
        n,
        [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
    )

    # Column 4: epoch_jd (float64 — Julian Date needs full precision)
    _write_float64(buf, n, [_required_float(o, "epoch_jd") for o in objects])

    # Column 5: q (float32, perihelion distance AU) — from SBDB
    _write_float32(buf, n, [_required_sbdb_float(o, "q") for o in objects])

    # Columns 6–9: e, i, om, w (float32)
    for attr in ("e", "i", "om", "w"):
        _write_float32(buf, n, [_required_float(o, attr) for o in objects])

    # Column 10: tp (float64 — Julian Date needs full precision) — from SBDB
    _write_float64(buf, n, [_required_sbdb_float(o, "tp") for o in objects])

    # Column 11: radius_km (float32)
    _write_float32(buf, n, [_radius_km(o, radius_km_overrides) for o in objects])

    out_file.write_bytes(gzip.compress(buf.getvalue()))


_ID_TYPE_ATTR: dict[str, str] = {
    "naif": "naif_id",
    "spkid": "spkid",
    "norad_satcat": "norad_cat_id",
}


def _parse_numeric_id(obj: Object) -> int:
    """Return the source-specific numeric ID for the binary export.

    Uses the proper column (naif_id, spkid, or
    norad_cat_id) based on the Object.id prefix (ID_TYPE).
    """
    # ID format: "{id_type}-{value}" (built by make_object_id)
    pos = obj.id.find("-")
    if pos == -1:
        logger.warning("%s: no separator in object ID", obj.id)
        return MISSING_INT32
    id_type = obj.id[:pos]

    attr = _ID_TYPE_ATTR.get(id_type)
    if attr is not None:
        val = getattr(obj, attr)
        if val is not None:
            return val
        logger.warning("%s: missing %s for binary export", obj.id, attr)
    else:
        logger.warning("%s: unknown ID type '%s' for numeric ID", obj.id, id_type)
    return MISSING_INT32


def _float_value(o: Object, attr: str) -> float:
    """Get the float64 value for a Keplerian column.

    Raises ValueError if a required element is missing, unless the orbit
    quality is known-bad (condition_code 9).
    """
    if attr in _REQUIRED_KEPLERIAN:
        val = getattr(o, attr)
        if val is None:
            sbdb = o.sbdb if o.spkid is not None else None
            if sbdb and sbdb.condition_code == "9":
                logger.warning("%s: missing required orbital element '%s'", o.id, attr)
            else:
                raise ValueError(f"{o.id}: missing required orbital element '{attr}'")
            return MISSING_FLOAT64
        return val
    val = getattr(o, attr)
    return val if val is not None else MISSING_FLOAT64


def _required_float(o: Object, attr: str) -> float:
    """Get a required float64 attribute, raising ValueError if missing."""
    val = getattr(o, attr)
    if val is None:
        raise ValueError(f"{o.id}: missing required element '{attr}'")
    return val


def _required_sbdb_float(o: Object, attr: str) -> float:
    """Get a required float64 from the SBDB relation, raising ValueError if missing."""
    sbdb = o.sbdb if o.spkid is not None else None
    if sbdb is None:
        raise ValueError(f"{o.id}: no SBDB data for parabolic element '{attr}'")
    val = getattr(sbdb, attr)
    if val is None:
        raise ValueError(f"{o.id}: parabolic comet missing '{attr}'")
    return val


def _required_celestrak_float(o: Object, attr: str) -> float:
    """Get a required float from the CelesTrak relation, raising ValueError if missing."""
    celestrak = o.celestrak if o.norad_cat_id is not None else None
    if celestrak is None:
        raise ValueError(f"{o.id}: no CelesTrak data for SGP4 field '{attr}'")
    val = getattr(celestrak, attr)
    if val is None:
        raise ValueError(f"{o.id}: CelesTrak missing required SGP4 field '{attr}'")
    return val


def _celestrak_int(o: Object, attr: str) -> int:
    """Get an optional int from the CelesTrak relation, returning MISSING_INT32 if absent."""
    celestrak = o.celestrak if o.norad_cat_id is not None else None
    if celestrak is None:
        return MISSING_INT32
    val = getattr(celestrak, attr)
    return val if val is not None else MISSING_INT32


def _radius_km(o: Object, overrides: dict[str, float] | None = None) -> float:
    """Get object radius in km from SBDB diameter or overrides."""
    if o.spkid is not None and o.sbdb is not None and o.sbdb.diameter is not None:
        return o.sbdb.diameter / 2.0
    if overrides and (r := overrides.get(o.id)):
        return r
    return MISSING_FLOAT64


def _write_int32(f, n: int, values: list[int]) -> None:
    f.write(struct.pack(f"<{n}i", *values))
    _pad8(f, n * 4)


def _write_uint8(f, n: int, values: list[int]) -> None:
    f.write(struct.pack(f"<{n}B", *values))
    _pad8(f, n)


def _write_float32(f, n: int, values: list[float]) -> None:
    f.write(struct.pack(f"<{n}f", *values))
    _pad8(f, n * 4)


def _write_float64(f, n: int, values: list[float]) -> None:
    f.write(struct.pack(f"<{n}d", *values))
    # float64 columns are always 8-byte aligned, no padding needed


def _pad8(f, written: int) -> None:
    pad = align8(written) - written
    if pad:
        f.write(b"\x00" * pad)
