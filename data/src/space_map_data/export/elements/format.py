"""Binary format constants for the elements.bin export."""

import struct

from space_map_data.models.object import ObjectType, ElementsScale

MAGIC = b"SMAP"
VERSION = 2
HEADER_SIZE = 16  # must be 8-byte aligned

# Format types (uint16 at header offset 6)
FORMAT_KEPLERIAN = 0  # Standard Keplerian elements (a, e, i, om, w, ma, n)
FORMAT_PARABOLIC = 1  # Parabolic elements (q, e, i, om, w, tp)
FORMAT_SGP4 = 2  # Keplerian columns + SGP4 fields (bstar, ndot, nddot, elsetno, revnum)

# ObjectType → uint8 ordinal (must match frontend format.ts)
OBJECT_TYPE_ORDINAL: dict[ObjectType, int] = {t: i for i, t in enumerate(ObjectType)}

# ElementsScale → uint8 ordinal
SCALE_ORDINAL: dict[ElementsScale, int] = {s: i for i, s in enumerate(ElementsScale)}

# Sentinel values for missing data
MISSING_INT32 = -1
MISSING_UINT8 = 255
MISSING_FLOAT64 = float("nan")


def pack_header(row_count: int, format_type: int = FORMAT_KEPLERIAN) -> bytes:
    """Pack the 16-byte file header."""
    return struct.pack(
        "<4sHHII",
        MAGIC,
        VERSION,
        format_type,
        row_count,
        0,  # reserved
    )


def align8(size: int) -> int:
    """Round up to next multiple of 8."""
    return (size + 7) & ~7
