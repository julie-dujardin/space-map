"""Tests for space_map_data.export.elements.format."""

import struct

from space_map_data.export.elements.format import (
    HEADER_SIZE,
    MAGIC,
    MISSING_FLOAT64,
    MISSING_INT32,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    VERSION,
    align8,
    pack_header,
)
from space_map_data.models.object import ElementsScale, ObjectType


class TestPackHeader:
    def test_returns_16_bytes(self):
        assert len(pack_header(0)) == 16

    def test_starts_with_magic(self):
        header = pack_header(0)
        assert header[:4] == MAGIC

    def test_row_count_round_trips(self):
        for count in (0, 1, 42, 100_000):
            header = pack_header(count)
            _magic, version, _reserved, row_count, _reserved2 = struct.unpack(
                "<4sHHII", header
            )
            assert row_count == count
            assert version == VERSION


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

    def test_sentinels(self):
        assert MISSING_INT32 == -1
        assert MISSING_UINT8 == 255
        assert MISSING_FLOAT64 != MISSING_FLOAT64  # NaN
