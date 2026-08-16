"""Tests for the nomenclature export writer."""

import gzip
import struct
from unittest.mock import MagicMock

import orjson
import pytest

from space_map_data.export.nomenclature.format import HEADER_SIZE, RECORD_SIZE
from space_map_data.export.nomenclature.writer import (
    FeatureDetailData,
    _build_labels,
    _build_positions,
    build_nomenclature,
    feature_bucket_key,
    hash_bucket,
    write_feature_detail_bundles,
    write_nomenclature_labels,
    write_nomenclature_positions,
)
from space_map_data.export.wikidata import WikidataEntityCache
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


class _StubWikidata(WikidataEntityCache):
    """Fake :class:`WikidataEntityCache` backed by a `{qid: {lang: label}}` map, skipping the on-disk init."""

    def __init__(self, labels_by_qid: dict[str, dict[str, str]] | None = None) -> None:
        self._labels_by_qid = labels_by_qid or {}

    def get_feature_entity(self, qid: str | None):
        if not qid or qid not in self._labels_by_qid:
            return None
        return {"labels": self._labels_by_qid[qid]}


class TestBuildLabels:
    def test_falls_back_to_iau_name_when_no_wikidata(self):
        feats = [_feat(feature_id=1, name="Tycho", wikidata_qid=None)]
        buf = _build_labels(feats, "en", _StubWikidata())
        assert buf.decode("utf-8").split("\n") == ["Tycho"]

    def test_uses_wikidata_label_when_present(self):
        feats = [
            _feat(feature_id=1, name="Abu Nuwas", wikidata_qid="Q1"),
            _feat(feature_id=2, name="Tycho", wikidata_qid="Q2"),
            _feat(feature_id=3, name="Mons Hadley", wikidata_qid="Q3"),
        ]
        wd = _StubWikidata(
            {
                "Q1": {"en": "Abu Nuwas (crater)", "ru": "Абу Нувас"},
                "Q2": {"en": "Tycho", "ru": "Тихо"},
                # Q3 has no labels for either language.
                "Q3": {},
            }
        )
        assert _build_labels(feats, "en", wd).decode("utf-8").split("\n") == [
            "Abu Nuwas (crater)",
            "Tycho",
            "Mons Hadley",
        ]
        assert _build_labels(feats, "ru", wd).decode("utf-8").split("\n") == [
            "Абу Нувас",
            "Тихо",
            "Mons Hadley",
        ]

    def test_ignores_unicode_name(self):
        # Per design: labels file uses the raw IAU `name`, not `unicode_name`.
        feats = [_feat(name="Asvaghosa", unicode_name="Aśvaghosa", wikidata_qid=None)]
        assert (
            _build_labels(feats, "en", _StubWikidata()).decode("utf-8") == "Asvaghosa"
        )

    def test_empty_input_emits_empty_bytes(self):
        assert _build_labels([], "en", _StubWikidata()) == b""


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

        by_body = build_nomenclature(session)

        assert set(by_body.keys()) == {"naif-301", "naif-499"}
        assert [f.feature_id for f in by_body["naif-301"]] == [1, 2]
        assert [f.feature_id for f in by_body["naif-499"]] == [3]


class TestWriteFiles:
    def test_writes_positions_per_body(self, tmp_path):
        by_body = {
            "naif-301": [_feat(feature_id=1, name="Tycho")],
            "naif-499": [_feat(feature_id=2, name="Olympus Mons")],
        }
        write_nomenclature_positions(tmp_path, by_body)
        for body_id, feats in by_body.items():
            pos_path = tmp_path / "nomenclature" / "positions" / f"{body_id}.bin.gz"
            assert pos_path.exists()
            buf = gzip.decompress(pos_path.read_bytes())
            assert len(buf) == HEADER_SIZE + len(feats) * RECORD_SIZE

    def test_writes_one_labels_file_per_lang_and_body(self, tmp_path):
        by_body = {
            "naif-301": [_feat(feature_id=1, name="Tycho")],
            "naif-499": [_feat(feature_id=2, name="Olympus Mons")],
        }
        write_nomenclature_labels(tmp_path, by_body, _StubWikidata())
        labels_root = tmp_path / "nomenclature" / "labels"
        for lang in ("en", "fr", "ja", "zh", "ar", "ru"):
            for body_id, feats in by_body.items():
                p = labels_root / lang / f"{body_id}.txt.gz"
                assert p.exists(), f"missing {p}"
                lines = gzip.decompress(p.read_bytes()).decode("utf-8").split("\n")
                assert lines == [f.name for f in feats]

    def test_labels_order_matches_positions_order(self, tmp_path):
        # The whole design hinges on this invariant: lines[i] ↔ position record[i].
        feats = [
            _feat(feature_id=42, name="Tycho"),
            _feat(feature_id=7, name="Copernicus"),
            _feat(feature_id=300, name="Mare Tranquillitatis"),
        ]
        by_body = {"naif-301": feats}
        write_nomenclature_positions(tmp_path, by_body)
        write_nomenclature_labels(tmp_path, by_body, _StubWikidata())

        pos_buf = gzip.decompress(
            (tmp_path / "nomenclature" / "positions" / "naif-301.bin.gz").read_bytes()
        )
        positions_ids: list[int] = []
        for i in range(len(feats)):
            offset = HEADER_SIZE + i * RECORD_SIZE
            (fid,) = struct.unpack("<I", pos_buf[offset : offset + 4])
            positions_ids.append(fid)

        for lang in ("en", "ru"):
            label_path = tmp_path / "nomenclature" / "labels" / lang / "naif-301.txt.gz"
            lines = gzip.decompress(label_path.read_bytes()).decode("utf-8").split("\n")
            assert len(lines) == len(positions_ids)
            # Same iteration order across both writers → join by index is sound.
            for fid, line, f in zip(positions_ids, lines, feats):
                assert fid == f.feature_id
                assert line == f.name

    def test_no_output_when_empty(self, tmp_path):
        write_nomenclature_positions(tmp_path, {})
        write_nomenclature_labels(tmp_path, {}, _StubWikidata())
        assert not (tmp_path / "nomenclature").exists()


class TestBucketKey:
    """feature_bucket_key + hash_bucket"""

    def test_key_format(self):
        assert feature_bucket_key("naif-301", 42) == "naif-301:42"

    def test_hash_bucket_deterministic(self):
        # Frontend reproduces this from the URL, so it must be stable across runs.
        for n in (1, 8, 50, 200):
            assert hash_bucket("naif-301:1234", n) == hash_bucket("naif-301:1234", n)

    def test_hash_bucket_range(self):
        for n in (1, 8, 50, 200):
            for fid in (1, 50, 1000, 999999):
                bucket = hash_bucket(feature_bucket_key("naif-499", fid), n)
                assert 0 <= bucket < n

    def test_features_distribute(self):
        # Dispersion should be near-uniform: not chi-squared exact, but many buckets used.
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
        for lang in ("ar", "fr", "ja", "ru", "zh"):
            assert ns[lang] == 0

        # Data is sharded across bucket files; reassemble to compare.
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
