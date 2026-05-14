"""Unified position-file binary format.

One magic, one common header, two payload variants. The format byte at offset 6
dispatches to either the columnar elements layout (Keplerian / Parabolic / SGP4)
or the per-body Chebyshev segment layout. A single file carries one format —
mixing was considered and rejected: the frontend can derive osculating elements
from Chebyshev positions when needed, so duplicating Kepler rows next to
Chebyshev segments would just bloat the export.

Common header (24 bytes, 8-aligned):

    Offset  Type     Field
    0       char[4]  magic = b"SMAP"
    4       uint16   version
    6       uint8    format            (0=elements, 1=chebyshev)
    7       uint8    reserved
    8       float64  start_jd          (file-level validity envelope, JD TDB)
    16      float64  end_jd

Then the format-specific extension (8 bytes, also 8-aligned), and the payload.

Elements extension (offsets 24..31):

    24      uint16   sub_format        (0=Kepler, 1=Parabolic, 2=SGP4)
    26      uint8    source            (provider ordinal; 255=unknown)
    27      uint8    id_type           (255=unknown)
    28      uint32   row_count

Chebyshev extension (offsets 24..31):

    24      uint32   body_count
    28      uint8    flags             (bit 0 = float64 coefficients)
    29      uint8    reserved (zero)
    30      uint16   reserved (zero)

Total header size is 32 bytes either way, matching the v6 layout so column
reading code at HEADER_SIZE=32 carries over unchanged.
"""

import math
import struct

from space_map_data.constants.providers import ID_TYPES
from space_map_data.models.object import ObjectType, ElementsScale, OrbitalSource

MAGIC = b"SMAP"
VERSION = 7

# Common header at offset 0..23, format extension at 24..31.
COMMON_HEADER_SIZE = 24
EXTENSION_SIZE = 8
HEADER_SIZE = COMMON_HEADER_SIZE + EXTENSION_SIZE  # 32 bytes, 8-aligned

# Top-level format byte at offset 6.
FORMAT_ELEMENTS = 0
FORMAT_CHEBYSHEV = 1
FORMAT_PROBES = 2

# Sub-chunk method ordinals (probes binary, per sub-chunk record).
METHOD_UNCOVERABLE = 0
METHOD_KEPLER_PURE = 1
METHOD_KEPLER_DRIFT = 2
METHOD_CHEBYSHEV = 3

# Elements sub-formats (uint16 at offset 24).
SUBFORMAT_KEPLERIAN = 0
SUBFORMAT_PARABOLIC = 1
SUBFORMAT_SGP4 = 2

# Sentinel bounds for files with no hard validity window. Keplerian/parabolic
# orbits are mathematical solutions valid for any jd; consumers compare against
# the window and treat ±inf as "always valid".
UNBOUNDED_START_JD = -math.inf
UNBOUNDED_END_JD = math.inf

OBJECT_TYPE_ORDINAL: dict[ObjectType, int] = {t: i for i, t in enumerate(ObjectType)}
SCALE_ORDINAL: dict[ElementsScale, int] = {s: i for i, s in enumerate(ElementsScale)}

# Pinned by name so the frontend mirror can't drift on Python enum re-ordering.
SOURCE_ORDINAL: dict[OrbitalSource, int] = {
    OrbitalSource.horizons: 0,
    OrbitalSource.sbdb: 1,
    OrbitalSource.celestrak: 2,
    OrbitalSource.spice: 3,
    OrbitalSource.sbdb_moon: 4,
    OrbitalSource.spice_probe: 5,
}

ID_TYPE_ORDINAL: dict[ID_TYPES, int] = {
    ID_TYPES.NAIF: 0,
    ID_TYPES.SPKID: 1,
    ID_TYPES.NORAD_SATCAT: 2,
    ID_TYPES.SBDB_MOON: 3,
    ID_TYPES.PROBE: 4,
}

MISSING_INT32 = -1
MISSING_UINT8 = 255
MISSING_FLOAT32 = float("nan")
MISSING_FLOAT64 = float("nan")
MISSING_SOURCE = 255
MISSING_ID_TYPE = 255

_COMMON_STRUCT = struct.Struct("<4sHBBdd")
assert _COMMON_STRUCT.size == COMMON_HEADER_SIZE

_ELEMENTS_EXT_STRUCT = struct.Struct("<HBBI")
assert _ELEMENTS_EXT_STRUCT.size == EXTENSION_SIZE

_CHEBYSHEV_EXT_STRUCT = struct.Struct("<IBBH")
assert _CHEBYSHEV_EXT_STRUCT.size == EXTENSION_SIZE

# bit 0 set ⇒ per-segment coefficients are stored as float64 instead of float32.
# Body header stays the same either way (segment_count + coeffs_per_axis are
# enough to size the payload once the dtype is known from the file header).
CHEBYSHEV_FLAG_FLOAT64_COEFFS = 0x01

# Probes extension (offsets 24..31):
#   24      uint32   probe_count
#   28      float32  subchunk_days        (from Zone.kepler_subchunk_days)
_PROBES_EXT_STRUCT = struct.Struct("<If")
assert _PROBES_EXT_STRUCT.size == EXTENSION_SIZE


def pack_elements_header(
    row_count: int,
    sub_format: int = SUBFORMAT_KEPLERIAN,
    source_ordinal: int = MISSING_SOURCE,
    id_type_ordinal: int = MISSING_ID_TYPE,
    start_jd: float = UNBOUNDED_START_JD,
    end_jd: float = UNBOUNDED_END_JD,
) -> bytes:
    """Pack the 32-byte header for an elements-payload file."""
    return _COMMON_STRUCT.pack(
        MAGIC, VERSION, FORMAT_ELEMENTS, 0, start_jd, end_jd
    ) + _ELEMENTS_EXT_STRUCT.pack(
        sub_format, source_ordinal, id_type_ordinal, row_count
    )


def pack_chebyshev_header(
    start_jd: float,
    end_jd: float,
    body_count: int,
    flags: int = 0,
) -> bytes:
    """Pack the 32-byte header for a chebyshev-payload file."""
    return _COMMON_STRUCT.pack(
        MAGIC, VERSION, FORMAT_CHEBYSHEV, 0, start_jd, end_jd
    ) + _CHEBYSHEV_EXT_STRUCT.pack(body_count, flags, 0, 0)


def pack_probes_header(
    start_jd: float,
    end_jd: float,
    probe_count: int,
    subchunk_days: float,
) -> bytes:
    """Pack the 32-byte header for a probes-payload file (format = 2)."""
    return _COMMON_STRUCT.pack(
        MAGIC, VERSION, FORMAT_PROBES, 0, start_jd, end_jd
    ) + _PROBES_EXT_STRUCT.pack(probe_count, float(subchunk_days))


# Per-probe header inside a probes-payload file (12 bytes, 4-aligned):
#
# Offset  Type     Field
# 0       int32    obj_id_value          (probe_id; recover full ID via id_type)
# 4       uint8    id_type               (ID_TYPE_ORDINAL[ID_TYPES.PROBE] = 4)
# 5       uint8    object_type           (ObjectType ordinal; always spacecraft today)
# 6       uint8    has_localized         (1 iff the probe has any Wikidata translation)
# 7       uint8    reserved
# 8       uint16   n_subchunks           (sub-chunk records that follow, in order)
# 10      uint16   first_subchunk_offset (in units of subchunk_days, from chunk start)
PROBE_HEADER_SIZE = 12
_PROBE_HEADER_STRUCT = struct.Struct("<iBBBBHH")
assert _PROBE_HEADER_STRUCT.size == PROBE_HEADER_SIZE


def pack_probe_header(
    probe_id: int,
    object_type_ordinal: int,
    has_localized: bool,
    n_subchunks: int,
    first_subchunk_offset: int,
) -> bytes:
    return _PROBE_HEADER_STRUCT.pack(
        probe_id,
        ID_TYPE_ORDINAL[ID_TYPES.PROBE],
        object_type_ordinal,
        1 if has_localized else 0,
        0,
        n_subchunks,
        first_subchunk_offset,
    )


# Per-sub-chunk record (8-byte fixed header + variable payload):
#
#   0  uint8  method        (0=uncoverable, 1=kepler_pure, 2=kepler_drift, 3=chebyshev)
#   1  uint8  reserved
#   2  uint16 reserved2
#   4  uint32 payload_len   (bytes following this header)
#   8  ...payload...
#
# Chose uint32 over uint16 because the finest-intlen chebyshev sub-chunks
# can hit ~67 KiB of coefficients (interplanetary 7-day sub-chunk × 0.03-d
# intlen × float64), which overflows uint16.
_SUBCHUNK_HEADER_STRUCT = struct.Struct("<BBHI")
SUBCHUNK_HEADER_SIZE = _SUBCHUNK_HEADER_STRUCT.size  # 8


def pack_subchunk_record(method_ordinal: int, payload: bytes) -> bytes:
    return _SUBCHUNK_HEADER_STRUCT.pack(method_ordinal, 0, 0, len(payload)) + payload


# Per-body chebyshev header (24 bytes, 8-aligned):
#
# Offset  Type     Field
# 0       int32    naif_id
# 4       int32    parent_id
# 8       int32    obj_id_value
# 12      float32  radius_km
# 16      uint16   coeffs_per_axis
# 18      uint8    id_type
# 19      uint8    has_localized       (1 iff the body has Wikidata in any language)
# 20      uint8    object_type         (ObjectType ordinal — same map as elements column 1)
# 21      uint8    reserved
# 22      uint16   segment_count       (uint16; ~200 segments per chunk in practice)
BODY_HEADER_SIZE = 24
_BODY_HEADER_STRUCT = struct.Struct("<iiifHBBBBH")
assert _BODY_HEADER_STRUCT.size == BODY_HEADER_SIZE


def pack_body_header(
    naif_id: int,
    parent_id: int,
    obj_id_value: int,
    radius_km: float,
    coeffs_per_axis: int,
    id_type_ordinal: int,
    has_localized: bool,
    object_type_ordinal: int,
    segment_count: int,
) -> bytes:
    return _BODY_HEADER_STRUCT.pack(
        naif_id,
        parent_id,
        obj_id_value,
        radius_km,
        coeffs_per_axis,
        id_type_ordinal,
        1 if has_localized else 0,
        object_type_ordinal,
        0,
        segment_count,
    )


def align8(size: int) -> int:
    """Round up to next multiple of 8."""
    return (size + 7) & ~7
