"""Binary format constants for the elements.bin export."""

import struct

from space_map_data.models.object import ObjectType, ElementsScale, OrbitalSource

MAGIC = b"SMAP"
VERSION = 1
HEADER_SIZE = 16  # must be 8-byte aligned

# Format types (uint16 at header offset 6)
FORMAT_KEPLERIAN = 0  # Standard Keplerian elements (a, e, i, om, w, ma, n)
FORMAT_PARABOLIC = 1  # Parabolic elements (q, e, i, om, w, tp)
FORMAT_SGP4 = 2  # Keplerian columns + SGP4 fields (bstar, ndot, nddot, elsetno, revnum)

# ObjectType → uint8 ordinal (must match frontend format.ts)
OBJECT_TYPE_ORDINAL: dict[ObjectType, int] = {t: i for i, t in enumerate(ObjectType)}

# ElementsScale → uint8 ordinal
SCALE_ORDINAL: dict[ElementsScale, int] = {s: i for i, s in enumerate(ElementsScale)}

# OrbitalSource → uint8 ordinal, stamped in the file header (offset 12).
# Pinned explicitly by name so the frontend mirror can't drift on Python enum
# re-ordering. MUST match the `OrbitalSource` enum in the frontend.
SOURCE_ORDINAL: dict[OrbitalSource, int] = {
    OrbitalSource.horizons: 0,
    OrbitalSource.sbdb: 1,
    OrbitalSource.celestrak: 2,
    OrbitalSource.spice: 3,
}

# Sentinel values for missing data
MISSING_INT32 = -1
MISSING_UINT8 = 255
MISSING_FLOAT64 = float("nan")
MISSING_SOURCE = 255  # placed in the header when a chunk has no declared source


def pack_header(
    row_count: int,
    format_type: int = FORMAT_KEPLERIAN,
    source_ordinal: int = MISSING_SOURCE,
) -> bytes:
    """Pack the 16-byte file header.

    Layout: magic(4) · version(u16) · format_type(u16) · row_count(u32) ·
    source(u8) · reserved(u8) · reserved(u16). Still 8-byte aligned.
    """
    return struct.pack(
        "<4sHHIBBH",
        MAGIC,
        VERSION,
        format_type,
        row_count,
        source_ordinal,
        0,  # reserved byte
        0,  # reserved u16
    )


def align8(size: int) -> int:
    """Round up to next multiple of 8."""
    return (size + 7) & ~7
