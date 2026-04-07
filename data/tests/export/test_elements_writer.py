"""Tests for space_map_data.export.elements.writer."""

import gzip
import math
import struct

from space_map_data.export.elements.format import (
    HEADER_SIZE,
    MAGIC,
    MISSING_INT32,
    VERSION,
)
from space_map_data.export.elements.writer import _parse_numeric_id, write_elements
from space_map_data.models.object import ObjectType
from tests.conftest import make_object


class TestParseNumericId:
    """_parse_numeric_id"""

    def test_naif_id(self):
        obj = make_object(id="naif-399")
        assert _parse_numeric_id(obj) == 399

    def test_sbdb_id(self):
        obj = make_object(id="sbdb:2000433")
        assert _parse_numeric_id(obj) == 2000433

    def test_negative_id(self):
        obj = make_object(id="naif--10")
        assert _parse_numeric_id(obj) == -10

    def test_no_match(self):
        obj = make_object(id="unknown")
        assert _parse_numeric_id(obj) == MISSING_INT32


def _read_header(data: bytes) -> tuple[bytes, int, int]:
    magic, version, _, row_count, _ = struct.unpack("<4sHHII", data[:HEADER_SIZE])
    return magic, version, row_count


class TestWriteElements:
    def test_round_trip(self, tmp_path):
        objects = [
            make_object(id="naif-399", object_type=ObjectType.planet),
            make_object(
                id="naif-499", name="Venus", object_type=ObjectType.planet, a=0.723
            ),
        ]
        out = tmp_path / "elements.bin.gz"
        write_elements(objects, out)

        raw = gzip.decompress(out.read_bytes())
        magic, version, row_count = _read_header(raw)
        assert magic == MAGIC
        assert version == VERSION
        assert row_count == 2

        # Read back column 0 (id, int32)
        offset = HEADER_SIZE
        ids = struct.unpack_from("<2i", raw, offset)
        assert ids == (399, 499)

    def test_empty(self, tmp_path):
        out = tmp_path / "empty.bin.gz"
        write_elements([], out)

        raw = gzip.decompress(out.read_bytes())
        _, _, row_count = _read_header(raw)
        assert row_count == 0
        assert len(raw) == HEADER_SIZE

    def test_radius_from_sbdb_diameter(self, tmp_path):
        """Object with SBDB diameter gets radius = diameter / 2."""
        from space_map_data.models.object.sbdb import SBDB

        sbdb = SBDB(spkid="2000433", object_id="sbdb:2000433", diameter=33.0)
        obj = make_object(
            id="sbdb:2000433",
            object_type=ObjectType.asteroid,
            sbdb_spkid=2000433,
        )
        obj.sbdb = sbdb

        out = tmp_path / "radius.bin.gz"
        write_elements([obj], out)

        raw = gzip.decompress(out.read_bytes())
        # radius_km is column 12 (last float64 column)
        # Compute offset: header + 13 columns of data for 1 row
        # col0: int32(1) + pad to 8 = 8
        # col1: uint8(1) + pad to 8 = 8
        # col2: int32(1) + pad to 8 = 8
        # col3: uint8(1) + pad to 8 = 8
        # cols 4-11: 8 x float64(1) = 8 x 8 = 64
        # col12: float64(1) = 8
        offset = HEADER_SIZE + 8 + 8 + 8 + 8 + 64  # start of col 12
        (radius,) = struct.unpack_from("<d", raw, offset)
        assert radius == 16.5  # 33.0 / 2

    def test_radius_override(self, tmp_path):
        """Object without SBDB but with a radius_km_override."""
        obj = make_object(id="naif-399", object_type=ObjectType.planet)

        out = tmp_path / "override.bin.gz"
        write_elements([obj], out, radius_km_overrides={"naif-399": 6371.0})

        raw = gzip.decompress(out.read_bytes())
        offset = HEADER_SIZE + 8 + 8 + 8 + 8 + 64
        (radius,) = struct.unpack_from("<d", raw, offset)
        assert radius == 6371.0

    def test_missing_radius(self, tmp_path):
        """Object without SBDB and no override gets NaN radius."""
        obj = make_object(id="naif-399", object_type=ObjectType.planet)

        out = tmp_path / "missing.bin.gz"
        write_elements([obj], out)

        raw = gzip.decompress(out.read_bytes())
        offset = HEADER_SIZE + 8 + 8 + 8 + 8 + 64
        (radius,) = struct.unpack_from("<d", raw, offset)
        assert math.isnan(radius)
