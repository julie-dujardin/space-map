"""Write the elements.bin binary file."""

import struct
from pathlib import Path

from space_map_data.export.format import (
    MISSING_FLOAT64,
    MISSING_INT32,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    align8,
    pack_header,
)
from space_map_data.models.object import Object


def write_elements(objects: list[Object], out_dir: Path) -> None:
    """Write elements.bin from a list of Objects (already sorted by eid)."""
    n = len(objects)
    out_file = out_dir / "elements.bin"

    with open(out_file, "wb") as f:
        f.write(pack_header(n))

        # Column 0: eid (int32) — sequential index
        _write_int32(f, n, [i for i in range(n)])

        # Column 1: object_type (uint8)
        _write_uint8(
            f,
            n,
            [OBJECT_TYPE_ORDINAL.get(o.object_type, MISSING_UINT8) for o in objects],
        )

        # Column 2: naif_id (int32) — object's own NAIF ID (for parent lookups)
        _write_int32(
            f,
            n,
            [o.horizons_naif_id if o.horizons_naif_id is not None else MISSING_INT32 for o in objects],
        )

        # Column 3: parent_naif_id (int32) — NAIF ID of parent body
        _write_int32(
            f,
            n,
            [o.parent_naif_id if o.parent_naif_id is not None else MISSING_INT32 for o in objects],
        )

        # Column 4: scale (uint8)
        _write_uint8(
            f,
            n,
            [SCALE_ORDINAL.get(o.scale, MISSING_UINT8) for o in objects],
        )

        # Columns 4–12: float64 columns
        float_attrs = ["epoch_jd", "a", "e", "i", "om", "w", "ma", "n", "radius_km"]
        for attr in float_attrs:
            _write_float64(
                f,
                n,
                [getattr(o, attr) if getattr(o, attr) is not None else MISSING_FLOAT64 for o in objects],
            )


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
