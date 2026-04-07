"""Write the elements.bin.gz binary file (gzip-compressed)."""

import gzip
import io
import logging
import re
import struct
from pathlib import Path

from space_map_data.export.elements.format import (
    MISSING_FLOAT64,
    MISSING_INT32,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    align8,
    pack_header,
)
from space_map_data.models.object import Object
from space_map_data.models.object.sbdb import OrbitClass

logger = logging.getLogger(__name__)

# Orbital element columns that the frontend needs to compute a position.
# Parabolic comets use q/tp instead of a/ma/n; checked separately.
_REQUIRED_KEPLERIAN = {"epoch_jd", "a", "e", "i", "om", "w", "ma", "n"}
_REQUIRED_PARABOLIC = {"e", "i", "om", "w"}


def write_elements(
    objects: list[Object],
    out_file: Path,
    radius_km_overrides: dict[str, float] | None = None,
) -> None:
    """Write a binary elements file from a list of Objects (already sorted).

    For parabolic comets (OrbitClass.PAR), the ``a`` slot carries perihelion
    distance *q* [AU] and the ``ma`` slot carries time of perihelion passage
    *tp* [JD].  The ``n`` slot is written as 0 (unused).  The frontend
    distinguishes these by zone name.

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

    # Columns 4–11: float64 orbital element columns
    # For parabolic comets: a→q, ma→tp, n→0 (see docstring)
    float_attrs = ["epoch_jd", "a", "e", "i", "om", "w", "ma", "n"]
    for attr in float_attrs:
        _write_float64(
            buf,
            n,
            [_float_value(o, attr) for o in objects],
        )

    # Column 12: radius_km — from SBDB diameter, or wikidata overrides
    def _radius_km(o: Object) -> float:
        if (
            o.sbdb_spkid is not None
            and o.sbdb is not None
            and o.sbdb.diameter is not None
        ):
            return o.sbdb.diameter / 2.0
        if radius_km_overrides and (r := radius_km_overrides.get(o.id)):
            return r
        return MISSING_FLOAT64

    _write_float64(buf, n, [_radius_km(o) for o in objects])

    out_file.write_bytes(gzip.compress(buf.getvalue()))


def _parse_numeric_id(obj: Object) -> int:
    """Extract the numeric ID from Object.id (e.g. 'naif-399' → 399, 'spkid-2000433' → 2000433)."""
    match = re.search(r"[-:](-?\d+)$", obj.id)
    if match:
        return int(match.group(1))
    return MISSING_INT32


def _float_value(o: Object, attr: str) -> float:
    """Get the float64 value for a column, remapping for parabolic comets.

    Raises ValueError if a required parabolic element (q/tp) is missing.
    Logs a warning and returns NaN for non-parabolic objects missing required
    elements (bad source data) — the frontend will skip these.
    """
    # o.sbdb will only be available if the table was joined
    sbdb = o.sbdb if o.sbdb_spkid is not None else None
    if sbdb is not None and sbdb.class_ == OrbitClass.PAR:
        if attr == "a":
            if sbdb.q is None:
                raise ValueError(
                    f"{o.id}: parabolic comet missing q (perihelion distance)"
                )
            return sbdb.q
        if attr == "ma":
            if sbdb.tp is None:
                raise ValueError(
                    f"{o.id}: parabolic comet missing tp (time of perihelion)"
                )
            return sbdb.tp
        if attr == "n":
            return MISSING_FLOAT64
        if attr in _REQUIRED_PARABOLIC:
            val = getattr(o, attr)
            if val is None:
                raise ValueError(
                    f"{o.id}: parabolic comet missing required element '{attr}'"
                )
            return val
    else:
        if attr in _REQUIRED_KEPLERIAN:
            val = getattr(o, attr)
            if val is None:
                # Acceptable if orbit is bad quality
                # One known case: SPKID 3137759 (2002 PD153)
                if sbdb and sbdb.condition_code == "9":
                    logger.warning(
                        "%s: missing required orbital element '%s'", o.id, attr
                    )
                else:
                    raise ValueError(
                        f"{o.id}: missing required orbital element '{attr}'"
                    )
                return MISSING_FLOAT64
            return val
    val = getattr(o, attr)
    return val if val is not None else MISSING_FLOAT64


def _write_int32(f, n: int, values: list[int]) -> None:
    f.write(struct.pack(f"<{n}i", *values))
    _pad8(f, n * 4)


def _write_uint8(f, n: int, values: list[int]) -> None:
    f.write(struct.pack(f"<{n}B", *values))
    _pad8(f, n)


def _write_float64(f, n: int, values: list[float]) -> None:
    f.write(struct.pack(f"<{n}d", *values))
    # float64 columns are always 8-byte aligned, no padding needed


def _pad8(f, written: int) -> None:
    pad = align8(written) - written
    if pad:
        f.write(b"\x00" * pad)
