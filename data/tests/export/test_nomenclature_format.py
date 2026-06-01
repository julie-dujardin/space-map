"""Tests for the SMNF nomenclature binary format."""

import struct

from space_map_data.export.nomenclature.format import (
    HEADER_SIZE,
    MAGIC,
    RECORD_SIZE,
    VERSION,
    _encode_type_code,
    pack_header,
    pack_record,
    quantize_lon_e7,
)


class TestPackHeader:
    def test_round_trip(self):
        buf = pack_header(42)
        assert len(buf) == HEADER_SIZE
        magic, version, _r0, _r1, count, _r2 = struct.unpack("<4sHBBII", buf)
        assert magic == MAGIC
        assert version == VERSION
        assert count == 42

    def test_zero_features(self):
        buf = pack_header(0)
        count = struct.unpack("<I", buf[8:12])[0]
        assert count == 0


class TestPackRecord:
    def test_round_trip(self):
        buf = pack_record(
            feature_id=15600,
            center_lat_e7=-203_000_000,
            center_lon_e7=3_500_000_000,
            diameter_m=92_000,
            type_code="AA",
        )
        assert len(buf) == RECORD_SIZE
        fid, lat, lon, diam, code, flags, _r = struct.unpack("<IiII2sBB", buf)
        assert fid == 15600
        assert lat == -203_000_000
        assert lon == 3_500_000_000
        assert diam == 92_000
        assert code == b"AA"
        assert flags == 0

    def test_flag_byte(self):
        buf = pack_record(1, 0, 0, 0, "MO", flags=1)
        flags = buf[18]
        assert flags == 1


class TestQuantizeLon:
    def test_east_positive_passes_through(self):
        assert quantize_lon_e7(358.1489) == 3_581_489_000

    def test_negative_wraps_to_east_positive(self):
        assert quantize_lon_e7(-11.36) == round((360.0 - 11.36) * 1e7)

    def test_zero(self):
        assert quantize_lon_e7(0.0) == 0

    def test_360_wraps_to_zero(self):
        assert quantize_lon_e7(360.0) == 0


class TestEncodeTypeCode:
    def test_two_char_code(self):
        assert _encode_type_code("AA") == b"AA"
        assert _encode_type_code("LI") == b"LI"

    def test_short_code_padded(self):
        assert _encode_type_code("X") == b"X\x00"

    def test_long_code_truncated(self):
        assert _encode_type_code("MONS") == b"MO"

    def test_non_ascii_replaced(self):
        assert _encode_type_code("Ä!") == b"?!"
