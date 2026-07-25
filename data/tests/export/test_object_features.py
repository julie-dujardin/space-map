"""Tests for the per-body surface-feature roll-up in the object bundles."""

import datetime
from unittest.mock import MagicMock

import pytest

from space_map_data.export.nomenclature.notable import NOTABLE_FEATURES
from space_map_data.export.objects.features import attach_notable_features
from space_map_data.export.objects.writer import ChunkObjectData
from space_map_data.export import notable
from space_map_data.models.feature import Feature


@pytest.fixture(autouse=True)
def no_images(monkeypatch: pytest.MonkeyPatch):
    """Thumbnails come from the real ingest cache; pin it empty."""
    monkeypatch.setattr(notable, "collect_feature_images", lambda _fid: None)


def _entities(labels: dict[str, dict[str, str]] | None = None) -> MagicMock:
    """Cache stub: QID → {lang: label}, with a sitelink per label."""
    by_qid = labels or {}

    def get_feature_entity(qid: str | None):
        if qid is None or qid not in by_qid:
            return None
        return {
            "labels": by_qid[qid],
            "sitelinks": {f"w{i}": "" for i in range(len(by_qid[qid]))},
        }

    cache = MagicMock()
    cache.get_feature_entity.side_effect = get_feature_entity
    return cache


def _feature(feature_id: int, **kwargs) -> Feature:
    defaults = {
        "feature_id": feature_id,
        "object_id": "naif-301",
        "name": f"Feature {feature_id}",
        "target": "moon",
        "center_lat": 0.0,
        "center_lon": 0.0,
        "diameter": 10.0,
        "feature_type_code": "AA",
        "approval_date": datetime.date(1970, 1, 1),
    }
    defaults.update(kwargs)
    return Feature(**defaults)


def _chunk(*object_ids: str, langs: tuple[str, ...] = ()) -> ChunkObjectData:
    chunk = ChunkObjectData()
    for object_id in object_ids:
        chunk.global_data[object_id] = {"id": object_id}
        for lang in langs:
            chunk.localized_data[lang][object_id] = {}
    return chunk


class TestAttachNotableFeatures:
    """`feature_count` + `notable_features` on the host's global bundle."""

    def test_counts_every_feature_and_ranks_by_prominence(self):
        chunk = _chunk("naif-301")
        by_body = {
            "naif-301": [
                _feature(1, name="Big anonymous", diameter=500.0),
                _feature(2, name="Tycho", diameter=85.0, wikidata_qid="Q1"),
                _feature(3, name="Small anonymous", diameter=5.0),
            ]
        }
        attach_notable_features(chunk, by_body, _entities({"Q1": {"en": "Tycho"}}))

        data = chunk.global_data["naif-301"]
        assert data["feature_count"] == 3
        assert [e["name"] for e in data["notable_features"]] == [
            "Tycho",
            "Big anonymous",
            "Small anonymous",
        ]

    def test_entries_route_to_the_feature_on_its_host(self):
        chunk = _chunk("naif-301")
        attach_notable_features(
            chunk,
            {"naif-301": [_feature(7, name="Tycho", diameter=85.29)]},
            _entities(),
        )

        assert chunk.global_data["naif-301"]["notable_features"] == [
            {
                "name": "Tycho",
                "id": "naif-301",
                "feature_id": 7,
                "diameter_km": 85.29,
                "first_obs": "1970-01-01",
            }
        ]

    def test_localized_names_land_only_where_the_body_has_an_entry(self):
        chunk = _chunk("naif-301", langs=("fr",))
        entities = _entities({"Q1": {"en": "Tycho", "fr": "Tycho (cratère)"}})
        attach_notable_features(
            chunk,
            {"naif-301": [_feature(7, name="Tycho", wikidata_qid="Q1")]},
            entities,
        )

        assert chunk.localized_data["fr"]["naif-301"]["notable_feature_names"] == {
            "naif-301:7": "Tycho (cratère)"
        }
        # No `ja` entry for this body → nothing to attach, and no crash.
        assert "naif-301" not in chunk.localized_data["ja"]

    def test_caps_the_notable_list(self):
        chunk = _chunk("naif-301")
        limit = NOTABLE_FEATURES
        by_body = {
            "naif-301": [_feature(i, diameter=float(i)) for i in range(limit + 5)]
        }
        attach_notable_features(chunk, by_body, _entities())

        data = chunk.global_data["naif-301"]
        assert data["feature_count"] == limit + 5
        assert len(data["notable_features"]) == limit

    def test_body_without_a_bundle_is_skipped(self, caplog):
        chunk = _chunk("naif-301")
        by_body = {
            "naif-301": [_feature(1)],
            "naif-999": [_feature(2, object_id="naif-999")],
        }
        attach_notable_features(chunk, by_body, _entities())

        assert "naif-999" not in chunk.global_data
        assert "naif-999" in caplog.text
