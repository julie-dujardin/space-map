"""Tests for the nomenclature export writer."""

import gzip
import struct
from unittest.mock import MagicMock

import orjson

from space_map_data.export.nomenclature.format import HEADER_SIZE, RECORD_SIZE
from space_map_data.export.nomenclature.writer import (
    _build_global,
    _build_positions,
    build_nomenclature,
    write_nomenclature_files,
)
from space_map_data.models.feature import Feature


def _feat(**kwargs) -> Feature:
    defaults = {
        "feature_id": 1,
        "object_id": "naif-301",
        "name": "Tycho",
        "target": "moon",
        "center_lat": -43.31,
        "center_lon": -11.36,
        "diameter": 85.29,
        "feature_type": "Crater, craters",
        "feature_type_code": "AA",
    }
    defaults.update(kwargs)
    return Feature(**defaults)


class TestBuildPositions:
    def test_header_and_records(self):
        feats = [
            _feat(feature_id=10, center_lat=0.0, center_lon=0.0, diameter=1.0),
            _feat(feature_id=11, center_lat=45.0, center_lon=-90.0, diameter=2.5),
        ]
        buf = _build_positions(feats)
        assert len(buf) == HEADER_SIZE + 2 * RECORD_SIZE
        count = struct.unpack("<I", buf[8:12])[0]
        assert count == 2
        rec0 = buf[HEADER_SIZE : HEADER_SIZE + RECORD_SIZE]
        fid, lat, lon, diam, code, _flags, _r = struct.unpack("<IiiI2sBB", rec0)
        assert fid == 10
        assert lat == 0
        assert lon == 0
        assert diam == 1000
        assert code == b"AA"

    def test_missing_diameter_is_zero(self):
        feats = [_feat(diameter=None)]
        buf = _build_positions(feats)
        diam = struct.unpack("<I", buf[HEADER_SIZE + 12 : HEADER_SIZE + 16])[0]
        assert diam == 0


class TestBuildGlobal:
    def test_picks_unicode_name(self):
        feats = [_feat(name="Plain", unicode_name="Plàin", approval_date="1935")]
        out = _build_global(feats)
        assert out["1"]["name"] == "Plàin"
        assert out["1"]["approval_date"] == "1935"

    def test_omits_none_fields(self):
        feats = [_feat(approval_date=None, origin=None, approval_status=None)]
        out = _build_global(feats)
        assert out["1"] == {"name": "Tycho"}


class TestBuildNomenclature:
    def test_groups_by_body_and_skips_invalid(self):
        rows = [
            _feat(feature_id=1, object_id="naif-301"),
            _feat(feature_id=2, object_id="naif-301"),
            _feat(feature_id=3, object_id="naif-499"),
            _feat(feature_id=4, object_id="naif-499", center_lat=None),
            _feat(feature_id=5, object_id="naif-499", feature_type_code=None),
        ]

        session = MagicMock()
        query_chain = MagicMock()
        session.query.return_value = query_chain
        query_chain.filter.return_value = query_chain
        query_chain.order_by.return_value = query_chain
        query_chain.all.return_value = rows
        query_chain.count.return_value = 0

        payload = build_nomenclature(session)

        assert set(payload.keys()) == {"naif-301", "naif-499"}
        moon_positions, moon_global = payload["naif-301"]
        moon_count = struct.unpack("<I", moon_positions[8:12])[0]
        assert moon_count == 2
        assert set(moon_global.keys()) == {"1", "2"}

        mars_positions, mars_global = payload["naif-499"]
        mars_count = struct.unpack("<I", mars_positions[8:12])[0]
        assert mars_count == 1
        assert set(mars_global.keys()) == {"3"}


class TestWriteFiles:
    def test_writes_gzipped_pairs(self, tmp_path):
        payload = {
            "naif-301": (b"positions-moon", {"1": {"name": "Tycho"}}),
            "naif-499": (b"positions-mars", {"2": {"name": "Olympus Mons"}}),
        }
        write_nomenclature_files(tmp_path, payload)

        for body_id in payload:
            pos_path = tmp_path / "nomenclature" / "positions" / f"{body_id}.bin.gz"
            glob_path = tmp_path / "nomenclature" / "__global__" / f"{body_id}.json.gz"
            assert pos_path.exists()
            assert glob_path.exists()
            assert gzip.decompress(pos_path.read_bytes()) == payload[body_id][0]
            assert (
                orjson.loads(gzip.decompress(glob_path.read_bytes()))
                == payload[body_id][1]
            )

    def test_no_output_when_empty(self, tmp_path):
        write_nomenclature_files(tmp_path, {})
        assert not (tmp_path / "nomenclature").exists()
