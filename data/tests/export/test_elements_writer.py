"""Tests for space_map_data.export.elements.writer."""

import gzip
import math
import struct

import pytest

from space_map_data.constants.providers import ID_TYPES
from space_map_data.export.elements.format import (
    FORMAT_KEPLERIAN,
    FORMAT_PARABOLIC,
    HEADER_SIZE,
    ID_TYPE_ORDINAL,
    MAGIC,
    MISSING_ID_TYPE,
    MISSING_INT32,
    SOURCE_ORDINAL,
    UNBOUNDED_END_JD,
    UNBOUNDED_START_JD,
    VERSION,
)
from space_map_data.export.elements.writer import (
    _parse_numeric_id,
    write_elements,
    write_parabolic_elements,
)
from space_map_data.models.object import ObjectType, OrbitalSource
from space_map_data.models.object.main import Object
from space_map_data.models.object.sbdb import OrbitClass, SBDB
from tests.conftest import make_object


class TestParseNumericId:
    """_parse_numeric_id uses source-specific columns instead of parsing Object.id."""

    def test_naif_id(self):
        obj = make_object(id="naif-399", naif_id=399)
        assert _parse_numeric_id(obj) == 399

    def test_spkid(self):
        obj = make_object(id="spkid-2000433", spkid=2000433)
        assert _parse_numeric_id(obj) == 2000433

    def test_norad_cat_id(self):
        obj = make_object(id="norad_satcat-25544", norad_cat_id=25544)
        assert _parse_numeric_id(obj) == 25544

    def test_negative_naif_id(self):
        obj = make_object(id="naif--31", naif_id=-31)
        assert _parse_numeric_id(obj) == -31

    def test_missing_column_returns_sentinel(self):
        obj = make_object(id="naif-399", naif_id=None)
        assert _parse_numeric_id(obj) == MISSING_INT32

    def test_unknown_id_type_returns_sentinel(self):
        obj = make_object(id="unknown-123")
        assert _parse_numeric_id(obj) == MISSING_INT32


def _read_header(
    data: bytes,
) -> tuple[bytes, int, int, float, float, int, int, int]:
    (
        magic,
        version,
        format_type,
        start_jd,
        end_jd,
        row_count,
        source,
        id_type,
        _res,
    ) = struct.unpack("<4sHHddIBBH", data[:HEADER_SIZE])
    return magic, version, format_type, start_jd, end_jd, row_count, source, id_type


class TestWriteElements:
    def test_round_trip(self, tmp_path):
        objects = [
            make_object(
                id="naif-399",
                naif_id=399,
                object_type=ObjectType.planet,
            ),
            make_object(
                id="naif-299",
                naif_id=299,
                name="Venus",
                object_type=ObjectType.planet,
                a=0.723,
            ),
        ]
        out = tmp_path / "elements.bin.gz"
        write_elements(objects, out, OrbitalSource.horizons, has_localized={})

        raw = gzip.decompress(out.read_bytes())
        (
            magic,
            version,
            format_type,
            start_jd,
            end_jd,
            row_count,
            source,
            id_type,
        ) = _read_header(raw)
        assert magic == MAGIC
        assert version == VERSION
        assert format_type == FORMAT_KEPLERIAN
        assert row_count == 2
        assert source == SOURCE_ORDINAL[OrbitalSource.horizons]
        assert id_type == ID_TYPE_ORDINAL[ID_TYPES.NAIF]
        # Keplerian defaults to unbounded validity — the orbit is mathematical
        # and stays valid for any jd.
        assert start_jd == UNBOUNDED_START_JD
        assert end_jd == UNBOUNDED_END_JD

        # Read back column 0 (id, int32)
        offset = HEADER_SIZE
        ids = struct.unpack_from("<2i", raw, offset)
        assert ids == (399, 299)

    def test_empty(self, tmp_path):
        out = tmp_path / "empty.bin.gz"
        write_elements([], out, OrbitalSource.horizons, has_localized={})

        raw = gzip.decompress(out.read_bytes())
        _, _, _, _, _, row_count, _, id_type = _read_header(raw)
        assert row_count == 0
        # Empty chunk has nothing to derive an id type from.
        assert id_type == MISSING_ID_TYPE
        assert len(raw) == HEADER_SIZE

    def test_custom_validity_window(self, tmp_path):
        """Caller-supplied start_jd/end_jd round-trip through the header."""
        out = tmp_path / "bounded.bin.gz"
        write_elements(
            [],
            out,
            OrbitalSource.horizons,
            has_localized={},
            start_jd=2460000.5,
            end_jd=2460100.5,
        )
        raw = gzip.decompress(out.read_bytes())
        _, _, _, start_jd, end_jd, _, _, _ = _read_header(raw)
        assert start_jd == 2460000.5
        assert end_jd == 2460100.5

    def test_source_mismatch_raises(self, tmp_path):
        """Row tagged with a different source than the chunk fails loudly."""
        objects = [
            make_object(
                id="naif-399",
                naif_id=399,
                object_type=ObjectType.planet,
                orbital_source=OrbitalSource.celestrak,
            ),
        ]
        with pytest.raises(ValueError, match="does not match chunk source"):
            write_elements(
                objects,
                tmp_path / "mismatch.bin.gz",
                OrbitalSource.horizons,
                has_localized={},
            )

    def test_id_type_mismatch_raises(self, tmp_path):
        """Mixed id-type rows in one chunk fail loudly: the header carries one byte."""
        objects = [
            make_object(id="naif-399", naif_id=399, object_type=ObjectType.planet),
            make_object(
                id="spkid-2000001",
                naif_id=None,
                spkid=2000001,
                object_type=ObjectType.asteroid,
            ),
        ]
        with pytest.raises(ValueError, match="does not match chunk id type"):
            write_elements(
                objects,
                tmp_path / "mixed.bin.gz",
                OrbitalSource.horizons,
                has_localized={},
            )

    def test_norad_id_type_in_header(self, tmp_path):
        """An earth-satellite chunk gets the NORAD_SATCAT id-type byte."""
        obj = make_object(
            id="norad_satcat-25544",
            naif_id=None,
            norad_cat_id=25544,
            object_type=ObjectType.spacecraft,
            orbital_source=OrbitalSource.celestrak,
        )
        out = tmp_path / "sat.bin.gz"
        write_elements([obj], out, OrbitalSource.celestrak, has_localized={})
        raw = gzip.decompress(out.read_bytes())
        _, _, _, _, _, _, _, id_type = _read_header(raw)
        assert id_type == ID_TYPE_ORDINAL[ID_TYPES.NORAD_SATCAT]

    def test_row_source_none_is_accepted(self, tmp_path):
        """Rows with orbital_source=None inherit the chunk header source."""
        obj = make_object(
            id="naif-399",
            naif_id=399,
            object_type=ObjectType.planet,
            orbital_source=None,
        )
        out = tmp_path / "none_src.bin.gz"
        write_elements([obj], out, OrbitalSource.spice, has_localized={})
        raw = gzip.decompress(out.read_bytes())
        _, _, _, _, _, _, source, _ = _read_header(raw)
        assert source == SOURCE_ORDINAL[OrbitalSource.spice]

    def test_radius_from_sbdb_diameter(self, tmp_path):
        """Object with SBDB diameter gets radius = diameter / 2."""
        from space_map_data.models.object.sbdb import SBDB

        sbdb = SBDB(spkid="2000433", object_id="spkid-2000433", diameter=33.0)
        obj = make_object(
            id="spkid-2000433",
            object_type=ObjectType.asteroid,
            spkid=2000433,
        )
        obj.sbdb = sbdb

        out = tmp_path / "radius.bin.gz"
        write_elements([obj], out, OrbitalSource.horizons, has_localized={})

        raw = gzip.decompress(out.read_bytes())
        # radius_km is column 12 (last float32 column)
        # Compute offset: header + 13 columns of data for 1 row
        # col0: int32(1) + pad to 8 = 8
        # col1: uint8(1) + pad to 8 = 8
        # col2: int32(1) + pad to 8 = 8
        # col3: uint8(1) + pad to 8 = 8
        # col4: epoch_jd float64(1) = 8
        # cols 5-11: 7 x float32(1) + pad to 8 = 7 x 8 = 56
        offset = HEADER_SIZE + 8 + 8 + 8 + 8 + 8 + 56  # start of col 12
        (radius,) = struct.unpack_from("<f", raw, offset)
        assert radius == 16.5  # 33.0 / 2

    def test_radius_override(self, tmp_path):
        """Object without SBDB but with a radius_km_override."""
        obj = make_object(id="naif-399", object_type=ObjectType.planet)

        out = tmp_path / "override.bin.gz"
        write_elements(
            [obj],
            out,
            OrbitalSource.horizons,
            radius_km_overrides={"naif-399": 6371.0},
            has_localized={},
        )

        raw = gzip.decompress(out.read_bytes())
        offset = HEADER_SIZE + 8 + 8 + 8 + 8 + 8 + 56
        (radius,) = struct.unpack_from("<f", raw, offset)
        assert radius == 6371.0

    def test_secular_drift_columns_round_trip(self, tmp_path):
        """om_dot/w_dot columns appended after radius round-trip as float32."""
        moon = make_object(
            id="naif-555",
            naif_id=555,
            object_type=ObjectType.moon,
            orbital_source=OrbitalSource.spice,
            om_dot=1.5,
            w_dot=-0.25,
        )
        # A row that doesn't populate the rates (e.g. a planet from SPICE
        # without a fitted secular model) must serialize as zero, not NaN —
        # that keeps the frontend's `om += om_dot·dt` step a no-op.
        planet = make_object(
            id="naif-399",
            naif_id=399,
            object_type=ObjectType.planet,
            orbital_source=OrbitalSource.spice,
        )
        out = tmp_path / "rates.bin.gz"
        write_elements([moon, planet], out, OrbitalSource.spice, has_localized={})
        raw = gzip.decompress(out.read_bytes())

        # Layout for 2 rows: cols 0-3 (8 bytes each, with padding) = 32, col 4
        # epoch_jd float64 = 16, cols 5-12 (8 float32 cols × 8 bytes) = 64.
        # om_dot (col 13) starts at HEADER_SIZE + 32 + 16 + 64 = HEADER_SIZE + 112.
        om_dot_offset = HEADER_SIZE + 32 + 16 + 64
        w_dot_offset = om_dot_offset + 8
        om_dot_vals = struct.unpack_from("<2f", raw, om_dot_offset)
        w_dot_vals = struct.unpack_from("<2f", raw, w_dot_offset)
        assert om_dot_vals == pytest.approx((1.5, 0.0))
        assert w_dot_vals == pytest.approx((-0.25, 0.0))

    def test_has_localized_column(self, tmp_path):
        """The trailing has_localized uint8 column round-trips with 1 for known
        ids and 0 for objects missing from the map."""
        a = make_object(
            id="naif-399",
            naif_id=399,
            object_type=ObjectType.planet,
            orbital_source=OrbitalSource.horizons,
        )
        b = make_object(
            id="naif-499",
            naif_id=499,
            object_type=ObjectType.planet,
            orbital_source=OrbitalSource.horizons,
        )
        out = tmp_path / "loc.bin.gz"
        write_elements(
            [a, b], out, OrbitalSource.horizons, has_localized={"naif-399": True}
        )
        raw = gzip.decompress(out.read_bytes())

        # Same Keplerian layout as the secular-drift test plus om_dot/w_dot
        # (cols 13–14, 8 bytes each for 2 rows). has_localized is column 15.
        offset = HEADER_SIZE + 32 + 16 + 64 + 8 + 8
        flags = struct.unpack_from("<2B", raw, offset)
        assert flags == (1, 0)

    def test_missing_radius(self, tmp_path):
        """Object without SBDB and no override gets NaN radius."""
        obj = make_object(id="naif-399", object_type=ObjectType.planet)

        out = tmp_path / "missing.bin.gz"
        write_elements([obj], out, OrbitalSource.horizons, has_localized={})

        raw = gzip.decompress(out.read_bytes())
        offset = HEADER_SIZE + 8 + 8 + 8 + 8 + 8 + 56
        (radius,) = struct.unpack_from("<f", raw, offset)
        assert math.isnan(radius)


def _make_parabolic_object(id: str = "spkid-1000001", **overrides) -> Object:
    """Create a parabolic comet Object with SBDB relation."""
    sbdb = SBDB(
        spkid="1000001",
        object_id=id,
        class_=OrbitClass.PAR,
        q=overrides.pop("sbdb_q", 1.5),
        tp=overrides.pop("sbdb_tp", 2460000.5),
    )
    obj = make_object(
        id=id,
        object_type=ObjectType.comet,
        spkid=1000001,
        e=1.0,
        # a/ma/n are meaningless for parabolic comets
        a=None,
        ma=None,
        n=None,
        orbital_source=OrbitalSource.sbdb,
        **overrides,
    )
    obj.sbdb = sbdb
    return obj


class TestWriteParabolicElements:
    """write_parabolic_elements"""

    def test_round_trip(self, tmp_path):
        obj = _make_parabolic_object()
        out = tmp_path / "par.bin.gz"
        write_parabolic_elements([obj], out, OrbitalSource.sbdb, has_localized={})

        raw = gzip.decompress(out.read_bytes())
        (
            magic,
            version,
            format_type,
            _start,
            _end,
            row_count,
            source,
            id_type,
        ) = _read_header(raw)
        assert magic == MAGIC
        assert version == VERSION
        assert format_type == FORMAT_PARABOLIC
        assert row_count == 1
        assert source == SOURCE_ORDINAL[OrbitalSource.sbdb]
        assert id_type == ID_TYPE_ORDINAL[ID_TYPES.SPKID]

    def test_q_and_tp_columns(self, tmp_path):
        """q and tp are written as proper columns (not stuffed into a/ma)."""
        obj = _make_parabolic_object(sbdb_q=2.3, sbdb_tp=2460100.5)
        out = tmp_path / "par.bin.gz"
        write_parabolic_elements([obj], out, OrbitalSource.sbdb, has_localized={})

        raw = gzip.decompress(out.read_bytes())
        # Parabolic layout for 1 row:
        # col0: int32(1) + pad = 8
        # col1: uint8(1) + pad = 8
        # col2: int32(1) + pad = 8
        # col3: uint8(1) + pad = 8
        # col4: epoch_jd float64 = 8
        # col5: q float32(1) + pad = 8
        # col6-9: e,i,om,w float32(1) + pad = 4 x 8 = 32
        # col10: tp float64 = 8
        # col11: radius_km float32(1) + pad = 8
        q_offset = HEADER_SIZE + 8 + 8 + 8 + 8 + 8  # after shared + epoch_jd
        (q,) = struct.unpack_from("<f", raw, q_offset)
        assert abs(q - 2.3) < 1e-6

        tp_offset = q_offset + 8 + 32  # skip q + e,i,om,w
        (tp,) = struct.unpack_from("<d", raw, tp_offset)
        assert tp == 2460100.5

    def test_empty(self, tmp_path):
        out = tmp_path / "par_empty.bin.gz"
        write_parabolic_elements([], out, OrbitalSource.sbdb, has_localized={})

        raw = gzip.decompress(out.read_bytes())
        _, _, format_type, _, _, row_count, _, _ = _read_header(raw)
        assert format_type == FORMAT_PARABOLIC
        assert row_count == 0
        assert len(raw) == HEADER_SIZE
