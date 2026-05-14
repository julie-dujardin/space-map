"""Tests for space_map_data.export.position.format."""

import math
import struct

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.position.format import (
    CHEBYSHEV_FLAG_FLOAT64_COEFFS,
    FORMAT_CHEBYSHEV,
    FORMAT_ELEMENTS,
    HEADER_SIZE,
    ID_TYPE_ORDINAL,
    MAGIC,
    MISSING_FLOAT64,
    MISSING_ID_TYPE,
    MISSING_INT32,
    MISSING_SOURCE,
    MISSING_UINT8,
    OBJECT_TYPE_ORDINAL,
    SCALE_ORDINAL,
    SOURCE_ORDINAL,
    SUBFORMAT_KEPLERIAN,
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
    VERSION,
    align8,
    pack_chebyshev_header,
    pack_elements_header,
)
from space_map_data.models.object import ElementsScale, ObjectType, OrbitalSource


def _unpack_elements(
    header: bytes,
) -> tuple[bytes, int, int, int, float, float, int, int, int, int]:
    """Unpack the 32-byte elements header (common 24 + extension 8)."""
    magic, version, top_format, _res = struct.unpack("<4sHBB", header[:8])
    start_jd, end_jd = struct.unpack("<dd", header[8:24])
    sub_format, source, id_type, row_count = struct.unpack("<HBBI", header[24:32])
    return (
        magic,
        version,
        top_format,
        sub_format,
        start_jd,
        end_jd,
        row_count,
        source,
        id_type,
        _res,
    )


def _unpack_chebyshev(header: bytes) -> tuple[bytes, int, int, float, float, int, int]:
    """Unpack the 32-byte chebyshev header (common 24 + extension 8)."""
    magic, version, top_format, _res = struct.unpack("<4sHBB", header[:8])
    start_jd, end_jd = struct.unpack("<dd", header[8:24])
    body_count, _res2 = struct.unpack("<II", header[24:32])
    return magic, version, top_format, start_jd, end_jd, body_count, _res2


class TestPackElementsHeader:
    def test_returns_32_bytes(self):
        assert len(pack_elements_header(0)) == 32

    def test_starts_with_magic(self):
        header = pack_elements_header(0)
        assert header[:4] == MAGIC

    def test_top_format_byte_is_elements(self):
        header = pack_elements_header(0)
        assert header[6] == FORMAT_ELEMENTS

    def test_row_count_round_trips(self):
        for count in (0, 1, 42, 100_000):
            header = pack_elements_header(count)
            _m, version, _t, _s, _start, _end, row_count, _src, _id, _r = (
                _unpack_elements(header)
            )
            assert row_count == count
            assert version == VERSION

    def test_source_byte_lands_at_offset_26(self):
        """Source ordinal is packed as uint8 at offset 26 (extension byte 2)."""
        header = pack_elements_header(
            0, source_ordinal=SOURCE_ORDINAL[OrbitalSource.celestrak]
        )
        assert header[26] == SOURCE_ORDINAL[OrbitalSource.celestrak]

    def test_default_source_is_missing_sentinel(self):
        header = pack_elements_header(0)
        _m, _v, _t, _s, _start, _end, _n, source, _id, _r = _unpack_elements(header)
        assert source == MISSING_SOURCE

    def test_id_type_byte_lands_at_offset_27(self):
        """Id-type ordinal is packed as uint8 at offset 27 (extension byte 3)."""
        header = pack_elements_header(
            0, id_type_ordinal=ID_TYPE_ORDINAL[ID_TYPES.NORAD_SATCAT]
        )
        assert header[27] == ID_TYPE_ORDINAL[ID_TYPES.NORAD_SATCAT]

    def test_default_id_type_is_missing_sentinel(self):
        header = pack_elements_header(0)
        _m, _v, _t, _s, _start, _end, _n, _source, id_type, _r = _unpack_elements(
            header
        )
        assert id_type == MISSING_ID_TYPE

    def test_default_validity_is_unbounded(self):
        """A file with no declared window gets ±inf — consumers treat as always valid."""
        header = pack_elements_header(0)
        _m, _v, _t, _s, start_jd, end_jd, _n, _src, _id, _r = _unpack_elements(header)
        assert start_jd == UNBOUNDED_START_JD
        assert math.isinf(start_jd) and start_jd < 0
        assert end_jd == UNBOUNDED_END_JD
        assert math.isinf(end_jd) and end_jd > 0

    def test_validity_window_round_trips(self):
        header = pack_elements_header(0, start_jd=2460000.5, end_jd=2460100.5)
        _m, _v, _t, _s, start_jd, end_jd, _n, _src, _id, _r = _unpack_elements(header)
        assert start_jd == 2460000.5
        assert end_jd == 2460100.5

    def test_subformat_round_trips(self):
        header = pack_elements_header(0, sub_format=SUBFORMAT_KEPLERIAN)
        _m, _v, _t, sub, _start, _end, _n, _src, _id, _r = _unpack_elements(header)
        assert sub == SUBFORMAT_KEPLERIAN


class TestPackChebyshevHeader:
    def test_returns_32_bytes(self):
        assert len(pack_chebyshev_header(0.0, 0.0, 0)) == 32

    def test_starts_with_magic(self):
        assert pack_chebyshev_header(0.0, 0.0, 0)[:4] == MAGIC

    def test_top_format_byte_is_chebyshev(self):
        assert pack_chebyshev_header(0.0, 0.0, 0)[6] == FORMAT_CHEBYSHEV

    def test_body_count_round_trips(self):
        for count in (0, 1, 42, 1000):
            header = pack_chebyshev_header(0.0, 0.0, count)
            _m, _v, _t, _start, _end, body_count, _r = _unpack_chebyshev(header)
            assert body_count == count

    def test_window_round_trips(self):
        header = pack_chebyshev_header(2460000.5, 2460100.5, 5)
        _m, _v, _t, start, end, _n, _r = _unpack_chebyshev(header)
        assert start == 2460000.5
        assert end == 2460100.5

    def test_flags_default_to_zero(self):
        header = pack_chebyshev_header(0.0, 0.0, 0)
        assert header[28] == 0

    def test_float64_flag_lands_at_offset_28(self):
        header = pack_chebyshev_header(
            0.0, 0.0, 0, flags=CHEBYSHEV_FLAG_FLOAT64_COEFFS
        )
        assert header[28] & CHEBYSHEV_FLAG_FLOAT64_COEFFS


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

    def test_id_type_ordinal_values_are_unique(self):
        """Frontend mirrors these ordinals to rebuild full IDs from numeric+flag."""
        assert len(set(ID_TYPE_ORDINAL.values())) == len(ID_TYPE_ORDINAL)
        assert MISSING_ID_TYPE not in ID_TYPE_ORDINAL.values()

    def test_id_type_ordinal_covers_active_types(self):
        """The three primary ID prefixes used in `Object.id` must all map."""
        assert ID_TYPES.NAIF in ID_TYPE_ORDINAL
        assert ID_TYPES.SPKID in ID_TYPE_ORDINAL
        assert ID_TYPES.NORAD_SATCAT in ID_TYPE_ORDINAL

    def test_top_format_constants_are_distinct(self):
        assert FORMAT_ELEMENTS != FORMAT_CHEBYSHEV

    def test_sentinels(self):
        assert MISSING_INT32 == -1
        assert MISSING_UINT8 == 255
        assert MISSING_FLOAT64 != MISSING_FLOAT64  # NaN
