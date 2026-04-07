"""Write the elements.bin.gz binary file (gzip-compressed)."""

import gzip
import io
import logging
import re
import struct
from pathlib import Path

from space_map_data.export.elements.format import (
    FORMAT_PARABOLIC,
    MISSING_FLOAT64,
    MISSING_INT32,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    align8,
    pack_header,
)
from space_map_data.models.object import Object

logger = logging.getLogger(__name__)

_REQUIRED_KEPLERIAN = {"epoch_jd", "a", "e", "i", "om", "w", "ma", "n"}


def write_elements(
    objects: list[Object],
    out_file: Path,
    radius_km_overrides: dict[str, float] | None = None,
) -> None:
    """Write a Keplerian binary elements file (format_type=0).

    Raises ValueError if a required orbital element is None — this catches
    data issues at export time rather than producing silent NaN in the binary.
    """
    n = len(objects)
    buf = io.BytesIO()

    buf.write(pack_header(n))

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
    float32_attrs = ["a", "e", "i", "om", "w", "ma", "n"]
    for attr in float32_attrs:
        _write_float32(
            buf,
            n,
            [_float_value(o, attr) for o in objects],
        )

    # Column 12: radius_km (float32)
    _write_float32(buf, n, [_radius_km(o, radius_km_overrides) for o in objects])

    out_file.write_bytes(gzip.compress(buf.getvalue()))


def write_parabolic_elements(
    objects: list[Object],
    out_file: Path,
    radius_km_overrides: dict[str, float] | None = None,
) -> None:
    """Write a parabolic binary elements file (format_type=1).

    Columns: id, object_type, parent_id, scale, epoch_jd, q, e, i, om, w, tp, radius_km.
    Raises ValueError if a required element (q, tp, e, i, om, w) is missing.
    """
    n = len(objects)
    buf = io.BytesIO()

    buf.write(pack_header(n, FORMAT_PARABOLIC))

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


def _parse_numeric_id(obj: Object) -> int:
    """Extract the numeric ID from Object.id (e.g. 'naif-399' → 399, 'spkid-2000433' → 2000433)."""
    match = re.search(r"[-:](-?\d+)$", obj.id)
    if match:
        return int(match.group(1))
    return MISSING_INT32


def _float_value(o: Object, attr: str) -> float:
    """Get the float64 value for a Keplerian column.

    Raises ValueError if a required element is missing, unless the orbit
    quality is known-bad (condition_code 9).
    """
    if attr in _REQUIRED_KEPLERIAN:
        val = getattr(o, attr)
        if val is None:
            sbdb = o.sbdb if o.sbdb_spkid is not None else None
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
    sbdb = o.sbdb if o.sbdb_spkid is not None else None
    if sbdb is None:
        raise ValueError(f"{o.id}: no SBDB data for parabolic element '{attr}'")
    val = getattr(sbdb, attr)
    if val is None:
        raise ValueError(f"{o.id}: parabolic comet missing '{attr}'")
    return val


def _radius_km(o: Object, overrides: dict[str, float] | None = None) -> float:
    """Get object radius in km from SBDB diameter or overrides."""
    if o.sbdb_spkid is not None and o.sbdb is not None and o.sbdb.diameter is not None:
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
