"""Tests for space_map_data.export.elements.format."""

import math
import struct

from space_map_data.export.elements.format import (
    FORMAT_KEPLERIAN,
    HEADER_SIZE,
    MAGIC,
    MISSING_FLOAT64,
    MISSING_INT32,
    MISSING_SOURCE,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    SOURCE_ORDINAL,
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
    VERSION,
    align8,
    pack_header,
)
from space_map_data.models.object import ElementsScale, ObjectType, OrbitalSource


def _unpack(header: bytes) -> tuple[bytes, int, int, float, float, int, int]:
    (
        magic,
        version,
        format_type,
        start_jd,
        end_jd,
        row_count,
        source,
        _pad,
        _res,
    ) = struct.unpack("<4sHHddIBBH", header)
    return magic, version, format_type, start_jd, end_jd, row_count, source


class TestPackHeader:
    def test_returns_32_bytes(self):
        assert len(pack_header(0)) == 32

    def test_starts_with_magic(self):
        header = pack_header(0)
        assert header[:4] == MAGIC

    def test_row_count_round_trips(self):
        for count in (0, 1, 42, 100_000):
            header = pack_header(count)
            _magic, version, _fmt, _start, _end, row_count, _source = _unpack(header)
            assert row_count == count
            assert version == VERSION

    def test_source_byte_lands_at_offset_28(self):
        """Source ordinal is packed as uint8 at header offset 28 (v3 layout)."""
        header = pack_header(
            0, FORMAT_KEPLERIAN, source_ordinal=SOURCE_ORDINAL[OrbitalSource.celestrak]
        )
        assert header[28] == SOURCE_ORDINAL[OrbitalSource.celestrak]

    def test_default_source_is_missing_sentinel(self):
        """A chunk with no declared source gets MISSING_SOURCE in the header."""
        header = pack_header(0)
        _magic, _v, _fmt, _start, _end, _n, source = _unpack(header)
        assert source == MISSING_SOURCE

    def test_default_validity_is_unbounded(self):
        """A chunk with no declared window gets ±inf — consumers treat as always valid."""
        header = pack_header(0)
        _magic, _v, _fmt, start_jd, end_jd, _n, _source = _unpack(header)
        assert start_jd == UNBOUNDED_START_JD
        assert math.isinf(start_jd) and start_jd < 0
        assert end_jd == UNBOUNDED_END_JD
        assert math.isinf(end_jd) and end_jd > 0

    def test_validity_window_round_trips(self):
        header = pack_header(0, start_jd=2460000.5, end_jd=2460100.5)
        _m, _v, _f, start_jd, end_jd, _n, _s = _unpack(header)
        assert start_jd == 2460000.5
        assert end_jd == 2460100.5


class TestAlign8:
    def test_already_aligned(self):
        assert align8(0) == 0
        assert align8(8) == 8
        assert align8(16) == 16

    def test_rounds_up(self):
        assert align8(1) == 8
        assert align8(7) == 8
        assert align8(9) == 16
        assert align8(13) == 16


class TestConstants:
    def test_header_size_is_8_aligned(self):
        assert HEADER_SIZE % 8 == 0

    def test_object_type_ordinal_covers_all(self):
        assert set(OBJECT_TYPE_ORDINAL.keys()) == set(ObjectType)

    def test_scale_ordinal_covers_all(self):
        assert set(SCALE_ORDINAL.keys()) == set(ElementsScale)

    def test_source_ordinal_covers_all(self):
        assert set(SOURCE_ORDINAL.keys()) == set(OrbitalSource)

    def test_source_ordinal_values_are_unique(self):
        """Frontend mirrors these ordinals — collisions would mis-attribute orbits."""
        assert len(set(SOURCE_ORDINAL.values())) == len(SOURCE_ORDINAL)
        assert MISSING_SOURCE not in SOURCE_ORDINAL.values()

    def test_sentinels(self):
        assert MISSING_INT32 == -1
        assert MISSING_UINT8 == 255
        assert MISSING_FLOAT64 != MISSING_FLOAT64  # NaN
