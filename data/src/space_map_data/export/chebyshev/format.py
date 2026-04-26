"""Binary format for chebyshev/{zone}/{chunk}/data.bin.

One file per (zone, time-chunk). Each body packs its own segment list inline so
consumers can pick the right segment via a simple interval search. Coefficient
arrays are little-endian float32 for size; time bounds stay float64 for JD
precision (see the Keplerian format's precision rationale).
"""

import struct

# Re-exported so consumers reading the body header can rebuild full object IDs
# without crossing into the elements module — the ordinal map is the single
# source of truth for both formats.
from space_map_data.export.elements.format import (
    ID_TYPE_ORDINAL,
    MISSING_ID_TYPE,
)

__all__ = [
    "MAGIC",
    "VERSION",
    "HEADER_SIZE",
    "BODY_HEADER_SIZE",
    "FORMAT_POSITION_ONLY",
    "MISSING_FLOAT32",
    "ID_TYPE_ORDINAL",
    "MISSING_ID_TYPE",
    "pack_header",
    "pack_body_header",
]

MAGIC = b"SCHB"
VERSION = 2

# Header layout — 32 bytes, 8-byte aligned.
#
# Offset  Type     Field
# 0       char[4]  magic = "SCHB"
# 4       uint16   version
# 6       uint16   format_type (0 = position-only Chebyshev)
# 8       float64  start_jd (chunk start, JD TDB)
# 16      float64  end_jd   (chunk end, exclusive, JD TDB)
# 24      uint32   body_count
# 28      uint32   reserved (zero)
HEADER_SIZE = 32
_HEADER_STRUCT = struct.Struct("<4sHHddII")
assert _HEADER_STRUCT.size == HEADER_SIZE

# Per-body header layout — 24 bytes, 8-byte aligned.
#
# Offset  Type     Field
# 0       int32    naif_id          (SPICE-side identifier; used for parent linking)
# 4       int32    parent_naif_id
# 8       int32    obj_id_value     (numeric portion of Object.id; equals naif_id when id_type=naif)
# 12      float32  radius_km        (NaN if unknown)
# 16      uint16   coeffs_per_axis  (= degree + 1)
# 18      uint8    id_type          (matches elements ID_TYPE_ORDINAL)
# 19      uint8    reserved
# 20      uint32   segment_count
#
# `id_type` + `obj_id_value` carry what `data.id.gz` used to encode out-of-band:
# Pluto/Ceres/perturber asteroids ship with id_type=spkid even though their
# SPICE naif_id is the planetary ID, so the frontend reconstructs e.g.
# "spkid-20134340" from those two fields rather than "naif-999".
BODY_HEADER_SIZE = 24
_BODY_HEADER_STRUCT = struct.Struct("<iiifHBBI")
assert _BODY_HEADER_STRUCT.size == BODY_HEADER_SIZE

# Per segment: start_jd (f64), end_jd (f64), then coeffs_per_axis × 3 × f32
# (order: x-coeffs, y-coeffs, z-coeffs). No padding needed — float64s are
# already 8-byte aligned, and 12 floats give 48 bytes (8-aligned).

FORMAT_POSITION_ONLY = 0

MISSING_FLOAT32 = float("nan")


def pack_header(start_jd: float, end_jd: float, body_count: int) -> bytes:
    return _HEADER_STRUCT.pack(
        MAGIC,
        VERSION,
        FORMAT_POSITION_ONLY,
        start_jd,
        end_jd,
        body_count,
        0,
    )


def pack_body_header(
    naif_id: int,
    parent_naif_id: int,
    obj_id_value: int,
    radius_km: float,
    coeffs_per_axis: int,
    id_type_ordinal: int,
    segment_count: int,
) -> bytes:
    return _BODY_HEADER_STRUCT.pack(
        naif_id,
        parent_naif_id,
        obj_id_value,
        radius_km,
        coeffs_per_axis,
        id_type_ordinal,
        0,
        segment_count,
    )
