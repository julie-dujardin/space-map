"""Binary format for chebyshev/{zone}/{chunk}/data.bin.

One file per (zone, time-chunk). Each body packs its own segment list inline so
consumers can pick the right segment via a simple interval search. Coefficient
arrays are little-endian float32 for size; time bounds stay float64 for JD
precision (see the Keplerian format's precision rationale).
"""

import struct

MAGIC = b"SCHB"
VERSION = 1

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

# Per-body header layout — 16 bytes, 4-byte aligned.
#
# Offset  Type     Field
# 0       int32    naif_id
# 4       int32    parent_naif_id
# 8       float32  radius_km (NaN if unknown)
# 12      uint16   coeffs_per_axis (= degree + 1)
# 14      uint16   reserved
# 16      uint32   segment_count
#
# Row order in the body table matches the sibling `data.id.gz` file, which
# carries the full `<source>-<numeric>` object IDs for linking to detail JSON
# (same convention as elements/{zone}/{zoom}/{part}.id.gz).
BODY_HEADER_SIZE = 20
_BODY_HEADER_STRUCT = struct.Struct("<iifHHI")
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
    radius_km: float,
    coeffs_per_axis: int,
    segment_count: int,
) -> bytes:
    return _BODY_HEADER_STRUCT.pack(
        naif_id,
        parent_naif_id,
        radius_km,
        coeffs_per_axis,
        0,
        segment_count,
    )
