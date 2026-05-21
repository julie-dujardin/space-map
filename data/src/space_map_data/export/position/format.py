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
VERSION = 8

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
# `METHOD_LANDED` records sit OUTSIDE the sub-chunk grid that 0..3 use — one
# trailing record per probe per chunk, gated by `PROBE_FLAG_HAS_LANDED_RECORD`
# in the probe header. Carries its own start/end ET offsets so its lifetime
# is decoupled from `subchunk_days × n_subchunks`.
METHOD_LANDED = 4

# Probe-header flags (byte 7).
PROBE_FLAG_HAS_LANDED_RECORD = 0x01

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


# Per-probe header inside a probes-payload file (20 bytes, 4-aligned):
#
# Offset  Type     Field
# 0       int32    obj_id_value          (probe_id; recover full ID via id_type)
# 4       uint8    id_type               (ID_TYPE_ORDINAL[ID_TYPES.PROBE] = 4)
# 5       uint8    object_type           (ObjectType ordinal; always spacecraft today)
# 6       uint8    has_localized         (1 iff the probe has any Wikidata translation)
# 7       uint8    flags                 (bit 0 = has trailing METHOD_LANDED record)
# 8       uint16   n_subchunks           (FLYING sub-chunk records that follow, in order)
# 10      uint16   first_subchunk_offset (in units of subchunk_days, from chunk start)
# 12      int32    fit_center_id_value   (alternate primary the fit is anchored
#                                         to; MISSING_INT32 = use zone default)
# 16      uint8    fit_center_id_type    (ID_TYPE_ORDINAL for fit_center_id_value;
#                                         MISSING_ID_TYPE = use zone default)
# 17      uint8[3] reserved              (zero pad to 4-aligned)
#
# fit_center lets a probe fit against its dominant primary (Moon, Titan,
# Vesta, …) instead of the zone center. NAIF for moons/planets, SPKID for
# asteroids — renderer composes `world = fit_center_world + probe_offset`.
PROBE_HEADER_SIZE = 20
_PROBE_HEADER_STRUCT = struct.Struct("<iBBBBHHiBxxx")
assert _PROBE_HEADER_STRUCT.size == PROBE_HEADER_SIZE


def pack_probe_header(
    probe_id: int,
    object_type_ordinal: int,
    has_localized: bool,
    n_subchunks: int,
    first_subchunk_offset: int,
    has_landed_record: bool = False,
    fit_center_id_value: int = MISSING_INT32,
    fit_center_id_type: int = MISSING_ID_TYPE,
) -> bytes:
    flags = PROBE_FLAG_HAS_LANDED_RECORD if has_landed_record else 0
    return _PROBE_HEADER_STRUCT.pack(
        probe_id,
        ID_TYPE_ORDINAL[ID_TYPES.PROBE],
        object_type_ordinal,
        1 if has_localized else 0,
        flags,
        n_subchunks,
        first_subchunk_offset,
        fit_center_id_value,
        fit_center_id_type,
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


# METHOD_LANDED payload — the trailing record that appears after a probe's
# flying sub-chunks when `PROBE_FLAG_HAS_LANDED_RECORD` is set:
#
# Offset  Type     Field
# 0       int32    body_naif_id      (body the probe sits on; 499 Mars, 606 Titan, …)
# 4       uint8    flags             (bit 0 = is_static)
# 5       uint8[3] reserved          (zero pad to 4-aligned)
# 8       uint32   start_offset_s    (seconds from chunk start_jd; phase entry within chunk)
# 12      uint32   end_offset_s      (seconds from chunk start_jd; phase exit within chunk)
# 16      int32    lat_ref_e7        (round(lat° × 1e7); reference / static position)
# 20      int32    lng_ref_e7
# 24      int32    alt_ref_mm        (mm above body reference ellipsoid)
# 28      uint32   sample_count      (0 for static — ref *is* the position)
# 32      sample_count × LANDED_SAMPLE_STRUCT (16 B each: et_offset_s + lat/lng/alt)
#
# Decode: lat° = lat_e7 / 1e7 → ~1.1 cm precision at Earth, 0.7 cm at Mars,
# well under the 0.1-m target on every body in `_IAU_FRAME`. The reference
# position uses the same encoding so the decoder never crosses encodings.
LANDED_HEADER_SIZE = 32
_LANDED_HEADER_STRUCT = struct.Struct("<iB3sIIiiiI")
assert _LANDED_HEADER_STRUCT.size == LANDED_HEADER_SIZE

LANDED_SAMPLE_SIZE = 16
_LANDED_SAMPLE_STRUCT = struct.Struct("<Iiii")
assert _LANDED_SAMPLE_STRUCT.size == LANDED_SAMPLE_SIZE

LANDED_FLAG_STATIC = 0x01
# Scale factor `lat_deg × LAT_LNG_SCALE → int32`. Picked as the largest power
# of 10 that still leaves int32 headroom for the full ±180° lng range (max
# value 1.8e9 vs int32 ceiling 2.147e9). Gives the same 1.1 cm precision floor
# everywhere — no body-radius dependency in the encoder.
LANDED_LATLNG_SCALE = 10_000_000  # 1e7


def _quantize_deg(deg: float) -> int:
    """Lat/lng degrees → int32 with 1e7 scale, clamped to int32 range."""
    return max(
        -2_147_483_647, min(2_147_483_647, int(round(deg * LANDED_LATLNG_SCALE)))
    )


def _quantize_alt_m(alt_m: float) -> int:
    """Altitude metres → int32 millimetres (range ±2,147 km — fits any body)."""
    return max(-2_147_483_647, min(2_147_483_647, int(round(alt_m * 1000.0))))


def pack_landed_payload(
    body_naif_id: int,
    is_static: bool,
    start_offset_s: int,
    end_offset_s: int,
    lat_ref_deg: float,
    lng_ref_deg: float,
    alt_ref_m: float,
    samples: list[tuple[int, float, float, float]],
) -> bytes:
    """Pack one METHOD_LANDED record.

    `samples` is a list of `(et_offset_s_from_chunk_start, lat_deg, lng_deg,
    alt_m)` tuples. For static phases pass an empty list — the reference
    fields carry the fixed position.

    Quantises to int32 × 1e7 for lat/lng (~1 cm precision globally) and
    int32 millimetres for altitude.
    """
    flags = LANDED_FLAG_STATIC if is_static else 0
    header = _LANDED_HEADER_STRUCT.pack(
        body_naif_id,
        flags,
        b"\x00\x00\x00",
        int(start_offset_s),
        int(end_offset_s),
        _quantize_deg(lat_ref_deg),
        _quantize_deg(lng_ref_deg),
        _quantize_alt_m(alt_ref_m),
        len(samples),
    )
    if not samples:
        return header
    sample_buf = bytearray(len(samples) * LANDED_SAMPLE_SIZE)
    for i, (et_offset_s, lat_deg, lng_deg, alt_m) in enumerate(samples):
        _LANDED_SAMPLE_STRUCT.pack_into(
            sample_buf,
            i * LANDED_SAMPLE_SIZE,
            int(et_offset_s),
            _quantize_deg(lat_deg),
            _quantize_deg(lng_deg),
            _quantize_alt_m(alt_m),
        )
    return header + bytes(sample_buf)
