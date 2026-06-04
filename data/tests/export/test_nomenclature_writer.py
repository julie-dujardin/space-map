"""Tests for the nomenclature export writer."""

import datetime
import gzip
import struct
from unittest.mock import MagicMock

import orjson
import pytest

from space_map_data.export.nomenclature.format import HEADER_SIZE, RECORD_SIZE
from space_map_data.export.nomenclature.writer import (
    FeatureDetailData,
    _build_global,
    _build_positions,
    build_nomenclature,
    feature_bucket_key,
    hash_bucket,
    write_feature_detail_bundles,
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
        fid, lat, lon, diam, code, _flags, _r = struct.unpack("<IiII2sBB", rec0)
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

    def test_iau_360_longitudes_round_trip(self):
        # IAU KML ships most bodies east-positive 0..360; uint32×1e7 fits.
        feats = [_feat(feature_id=42, center_lon=358.1489)]
        buf = _build_positions(feats)
        lon_e7 = struct.unpack("<I", buf[HEADER_SIZE + 8 : HEADER_SIZE + 12])[0]
        assert lon_e7 / 1e7 == pytest.approx(358.1489, abs=1e-4)

    def test_negative_longitudes_wrap_to_east_positive(self):
        feats = [_feat(feature_id=43, center_lon=-11.36)]
        buf = _build_positions(feats)
        lon_e7 = struct.unpack("<I", buf[HEADER_SIZE + 8 : HEADER_SIZE + 12])[0]
        assert lon_e7 / 1e7 == pytest.approx(348.64, abs=1e-4)


class TestBuildGlobal:
    def test_picks_unicode_name(self):
        feats = [
            _feat(
                name="Plain",
                unicode_name="Plàin",
                approval_date=datetime.date(1935, 1, 1),
            )
        ]
        out = _build_global(feats)
        assert out["1"]["name"] == "Plàin"
        assert out["1"]["approval_date"] == "1935-01-01"

    def test_omits_none_fields(self):
        feats = [_feat(approval_date=None, origin=None)]
        out = _build_global(feats)
        assert out["1"] == {"name": "Tycho"}

    def test_parent_feature_id_included_when_set(self):
        feats = [_feat(feature_id=10, parent_feature_id=5)]
        out = _build_global(feats)
        assert out["10"]["parent_feature_id"] == 5


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


class TestBucketKey:
    """feature_bucket_key + hash_bucket"""

    def test_key_format(self):
        assert feature_bucket_key("naif-301", 42) == "naif-301:42"

    def test_hash_bucket_deterministic(self):
        # The frontend reproduces this from the URL — the bucket math must
        # be stable across runs.
        for n in (1, 8, 50, 200):
            assert hash_bucket("naif-301:1234", n) == hash_bucket("naif-301:1234", n)

    def test_hash_bucket_range(self):
        for n in (1, 8, 50, 200):
            for fid in (1, 50, 1000, 999999):
                bucket = hash_bucket(feature_bucket_key("naif-499", fid), n)
                assert 0 <= bucket < n

    def test_features_distribute(self):
        # Hash dispersion across bodies & feature ids should be near-uniform —
        # not a perfect chi-squared but at least uses many buckets.
        n = 50
        used = {
            hash_bucket(feature_bucket_key(f"naif-{body}", fid), n)
            for body in (199, 299, 301, 499, 599)
            for fid in range(0, 200)
        }
        assert len(used) >= n - 5  # allow a few empty buckets


class TestWriteFeatureDetailBundles:
    def test_emits_bucket_files_keyed_correctly(self, tmp_path):
        details = FeatureDetailData()
        details.global_data["naif-301:1"] = {"wikidata_qid": "Q1000036"}
        details.global_data["naif-301:2"] = {"wikidata_qid": "Q9999"}
        details.localized_data["en"]["naif-301:1"] = {"description": "lunar crater"}

        ns = write_feature_detail_bundles(tmp_path, details)

        assert ns["global"] >= 1
        assert ns["en"] >= 1
        # Every other lang should report 0 buckets
        for lang in ("ar", "fr", "ja", "ru", "zh"):
            assert ns[lang] == 0

        # Decompose what we wrote: bucket file names match the hashed key
        global_dir = tmp_path / "nomenclature" / "details" / "__global__"
        assert global_dir.exists()
        gathered: dict[str, dict] = {}
        for f in global_dir.glob("*.json.gz"):
            gathered.update(orjson.loads(gzip.decompress(f.read_bytes())))
        assert gathered == details.global_data

        en_dir = tmp_path / "nomenclature" / "details" / "en"
        assert en_dir.exists()
        en_gathered: dict[str, dict] = {}
        for f in en_dir.glob("*.json.gz"):
            en_gathered.update(orjson.loads(gzip.decompress(f.read_bytes())))
        assert en_gathered == details.localized_data["en"]

    def test_empty_details_writes_nothing(self, tmp_path):
        ns = write_feature_detail_bundles(tmp_path, FeatureDetailData())
        assert ns["global"] == 0
        for lang in ("ar", "en", "fr", "ja", "ru", "zh"):
            assert ns[lang] == 0
        assert not (tmp_path / "nomenclature" / "details").exists()
