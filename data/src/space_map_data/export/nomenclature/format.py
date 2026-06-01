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
    4       int32    center_lat_e7        (deg × 1e7)
    8       int32    center_lon_e7        (deg × 1e7; planetographic)
    12      uint32   diameter_m           (metres; 0 when unknown)
    16      char[2]  type_code            (ASCII IAU 2-letter code)
    18      uint8    flags                (reserved)
    19      uint8    reserved (0)

Lat/lon quantisation reuses ``quantize_deg`` from ``export/position/format.py``
so the encoding stays consistent with landed-probe records.
"""

import struct

MAGIC = b"SMNF"
VERSION = 1

HEADER_SIZE = 16
RECORD_SIZE = 20

_HEADER_STRUCT = struct.Struct("<4sHBBII")
assert _HEADER_STRUCT.size == HEADER_SIZE

_RECORD_STRUCT = struct.Struct("<IiiI2sBB")
assert _RECORD_STRUCT.size == RECORD_SIZE


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
    """Pack one per-feature record. Lat/lon already quantised by caller."""
    return _RECORD_STRUCT.pack(
        feature_id,
        center_lat_e7,
        center_lon_e7,
        diameter_m,
        _encode_type_code(type_code),
        flags,
        0,
    )
