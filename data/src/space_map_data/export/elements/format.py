"""Binary format constants for the elements.bin export."""

import math
import struct

from space_map_data.constants.providers import ID_TYPES
from space_map_data.models.object import ObjectType, ElementsScale, OrbitalSource

MAGIC = b"SMAP"
VERSION = 4
HEADER_SIZE = 32  # must be 8-byte aligned

# Sentinel bounds for chunks with no hard validity window (e.g. Keplerian
# orbits mathematically valid for any jd). Consumers compare `jd` against the
# window — positive/negative infinity short-circuits as "always valid".
UNBOUNDED_START_JD = -math.inf
UNBOUNDED_END_JD = math.inf

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

# ID_TYPES → uint8 ordinal, stamped in the file header (offset 29). The chunk
# is single-typed by construction (each (zone, zoom) query in export/common.py
# selects on the id-type-defining column) so one byte per file is enough; the
# frontend rebuilds the full `<prefix>-<numeric>` from this byte and column 0.
# Pinned by name — frontend mirror MUST match.
ID_TYPE_ORDINAL: dict[ID_TYPES, int] = {
    ID_TYPES.NAIF: 0,
    ID_TYPES.SPKID: 1,
    ID_TYPES.NORAD_SATCAT: 2,
}

# Sentinel values for missing data
MISSING_INT32 = -1
MISSING_UINT8 = 255
MISSING_FLOAT64 = float("nan")
MISSING_SOURCE = 255  # placed in the header when a chunk has no declared source
MISSING_ID_TYPE = 255  # placed in the header when a chunk has no declared id type


def pack_header(
    row_count: int,
    format_type: int = FORMAT_KEPLERIAN,
    source_ordinal: int = MISSING_SOURCE,
    id_type_ordinal: int = MISSING_ID_TYPE,
    start_jd: float = UNBOUNDED_START_JD,
    end_jd: float = UNBOUNDED_END_JD,
) -> bytes:
    """Pack the 32-byte file header.

    Layout: magic(4) · version(u16) · format_type(u16) · start_jd(f64) ·
    end_jd(f64) · row_count(u32) · source(u8) · id_type(u8) · reserved(u16).
    Mirrors the Chebyshev header so both formats carry the same chunk-level
    validity window; ±inf means unbounded.
    """
    return struct.pack(
        "<4sHHddIBBH",
        MAGIC,
        VERSION,
        format_type,
        start_jd,
        end_jd,
        row_count,
        source_ordinal,
        id_type_ordinal,
        0,  # reserved u16
    )


def align8(size: int) -> int:
    """Round up to next multiple of 8."""
    return (size + 7) & ~7
