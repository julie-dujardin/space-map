"""Write the elements.bin binary file."""

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


def _parse_numeric_id(obj: Object) -> int:
    """Extract the numeric ID from Object.id (e.g. 'naif-399' → 399, 'spkid-2000433' → 2000433)."""
    match = re.search(r"[-:](-?\d+)$", obj.id)
    if match:
        return int(match.group(1))
    return MISSING_INT32


def write_elements(objects: list[Object], out_dir: Path) -> None:
    """Write elements.bin from a list of Objects (already sorted)."""
    n = len(objects)
    out_file = out_dir / "elements.bin"

    with open(out_file, "wb") as f:
        f.write(pack_header(n))

        # Column 0: id (int32) — type-specific ID from Object.id
        _write_int32(f, n, [_parse_numeric_id(o) for o in objects])

        # Column 1: object_type (uint8)
        _write_uint8(
            f,
            n,
            [OBJECT_TYPE_ORDINAL.get(o.object_type, MISSING_UINT8) for o in objects],
        )

        # Column 2: parent_id (int32) — NAIF ID of parent body
        _write_int32(
            f,
            n,
            [
                o.parent_naif_id if o.parent_naif_id is not None else MISSING_INT32
                for o in objects
            ],
        )

        # Column 3: scale (uint8)
        _write_uint8(
            f,
            n,
            [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
        )

        # Columns 4–11: float64 orbital element columns
        float_attrs = ["epoch_jd", "a", "e", "i", "om", "w", "ma", "n"]
        for attr in float_attrs:
            _write_float64(
                f,
                n,
                [
                    getattr(o, attr)
                    if getattr(o, attr) is not None
                    else MISSING_FLOAT64
                    for o in objects
                ],
            )

        # Column 12: radius_km — derived from SBDB diameter at export time
        def _radius_km(o: Object) -> float:
            if o.sbdb is not None and o.sbdb.diameter is not None:
                return o.sbdb.diameter / 2.0
            return MISSING_FLOAT64

        _write_float64(f, n, [_radius_km(o) for o in objects])


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
