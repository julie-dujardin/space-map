"""Probe-attitude binary chunk format.

One file per (probe, time-window). Header carries the absolute start time;
keyframes are time-delta-encoded smallest-three quaternions. The decoder
walks keyframes, accumulates `dt_seconds` to recover absolute ET, and
SLERPs between bracketing pairs to get attitude at any time in the window.

Header (16 bytes, 8-aligned):

    Offset  Type      Field
    0       char[4]   magic = b"ATTI"
    4       uint16    version
    6       uint8     reserved
    7       uint8     reserved
    8       float64   start_jd        (JD TDB of the first keyframe)

Keyframe (11 bytes, packed back-to-back after the header):

    0       float32   dt_seconds      (offset from previous; first kf = 0)
    4       uint8     idx             (0..3 — dropped quat component index)
    5       int16     a               (one of the kept components × 32767)
    7       int16     b
    9       int16     c

Reconstruction: the missing component is recovered as
`sqrt(max(0, 1 - a² - b² - c²))`, with `idx` telling the decoder which slot.

`dt` is float32: an integer-second quantum accumulated multi-minute drift
across a chunk of sub-second-spaced keyframes.

Spin baseline (when used) lives in the per-probe manifest, not the file —
every chunk for a probe shares it, so duplicating it per chunk would waste
bytes.
"""

import struct

# Magic ≠ "SMAP" so that a misrouted attitude file can't masquerade as a
# position file in the existing readers. Distinct constant, distinct
# version counter — independent evolution from position formats.
MAGIC = b"ATTI"
VERSION = 2

HEADER_SIZE = 16
KEYFRAME_SIZE = 11

_HEADER_STRUCT = struct.Struct("<4sHBBd")
assert _HEADER_STRUCT.size == HEADER_SIZE

# Little-endian: dt_seconds (float32), idx (uint8), a/b/c (int16×3).
# `<` so we match position files; no native alignment surprises.
_KF_STRUCT = struct.Struct("<fBhhh")
assert _KF_STRUCT.size == KEYFRAME_SIZE

# int16 scale used to quantise the three kept quaternion components from
# the ±1 unit interval. 32767 = max positive int16; -32767 lower bound so
# the encoding is symmetric (int16 min -32768 unused as a sign sentinel).
COMPONENT_SCALE = 32767


def pack_header(start_jd: float) -> bytes:
    """Pack the 16-byte file header."""
    return _HEADER_STRUCT.pack(MAGIC, VERSION, 0, 0, float(start_jd))


def unpack_header(buf: bytes) -> tuple[int, float]:
    """Validate magic + return (version, start_jd) from `buf[:HEADER_SIZE]`."""
    magic, version, _r0, _r1, start_jd = _HEADER_STRUCT.unpack(buf[:HEADER_SIZE])
    if magic != MAGIC:
        raise ValueError(f"bad attitude file magic: {magic!r}")
    return version, float(start_jd)


def pack_keyframe(dt_seconds: float, idx: int, a: int, b: int, c: int) -> bytes:
    """Pack one keyframe record. Components must be pre-scaled int16."""
    return _KF_STRUCT.pack(float(dt_seconds), int(idx), int(a), int(b), int(c))


def unpack_keyframe(buf: bytes, offset: int) -> tuple[float, int, int, int, int]:
    """Unpack one keyframe at `offset`. Returns (dt_seconds, idx, a, b, c)."""
    return _KF_STRUCT.unpack_from(buf, offset)


def quantise_component(value: float) -> int:
    """Clamp a quaternion component (∈ [-1, 1]) and scale to int16 range."""
    return max(
        -COMPONENT_SCALE, min(COMPONENT_SCALE, int(round(value * COMPONENT_SCALE)))
    )


def dequantise_component(value: int) -> float:
    """Inverse of `quantise_component` — used by decoders and tests."""
    return value / COMPONENT_SCALE
