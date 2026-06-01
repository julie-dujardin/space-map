"""Binary format for IAU planetary nomenclature features.

Static surface coordinates — no JD validity envelope, so a sibling format
from SMAP rather than a third dispatch on the format byte.

File header (16 bytes, 4-aligned):

    Offset  Type     Field
    0       char[4]  magic = b"SMNF"
    4       uint16   version
    6       uint8    reserved (0)
    7       uint8    reserved (0)
    8       uint32   feature_count
    12      uint32   reserved (0)

Per-feature record (20 bytes, 4-aligned):

    Offset  Type     Field
    0       uint32   feature_id
    4       int32    center_lat_e7        (deg × 1e7; planetographic, ±90)
    8       uint32   center_lon_e7        (deg × 1e7; planetographic, east-positive 0..360)
    12      uint32   diameter_m           (metres; 0 when unknown)
    16      char[2]  type_code            (ASCII IAU 2-letter code)
    18      uint8    flags                (reserved)
    19      uint8    reserved (0)

Latitude reuses ``quantize_deg`` from ``export/position/format.py`` (int32×1e7,
matches landed-probe records). Longitude is uint32×1e7 — IAU planetographic
ships east-positive 0..360, and the unsigned range fits the full 360°
(int32×1e7 would saturate above ~214.75°).
"""

import struct

MAGIC = b"SMNF"
VERSION = 1

HEADER_SIZE = 16
RECORD_SIZE = 20

_HEADER_STRUCT = struct.Struct("<4sHBBII")
assert _HEADER_STRUCT.size == HEADER_SIZE

_RECORD_STRUCT = struct.Struct("<IiII2sBB")
assert _RECORD_STRUCT.size == RECORD_SIZE


def quantize_lon_e7(lon_deg: float) -> int:
    """Lon degrees → uint32×1e7, wrapped to east-positive [0, 360).

    Tolerant of ±180 inputs (Python's ``%`` returns non-negative for a
    positive divisor) — any body's lon convention round-trips into the
    SMNF east-positive form.
    """
    return int(round((lon_deg % 360.0) * 1e7))


def pack_header(feature_count: int) -> bytes:
    """Pack the 16-byte file header."""
    return _HEADER_STRUCT.pack(MAGIC, VERSION, 0, 0, feature_count, 0)


def _encode_type_code(code: str) -> bytes:
    """ASCII-encode an IAU type code to a 2-byte slot, null-padded."""
    raw = code.encode("ascii", errors="replace")[:2]
    return raw.ljust(2, b"\x00")


def pack_record(
    feature_id: int,
    center_lat_e7: int,
    center_lon_e7: int,
    diameter_m: int,
    type_code: str,
    flags: int = 0,
) -> bytes:
    """Pack one per-feature record. Lat is int32, lon is uint32 (0..360°),
    both already quantised at 1e7 by caller."""
    return _RECORD_STRUCT.pack(
        feature_id,
        center_lat_e7,
        center_lon_e7,
        diameter_m,
        _encode_type_code(type_code),
        flags,
        0,
    )
