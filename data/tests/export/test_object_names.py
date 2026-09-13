"""Tests for the curated object-name overrides in export.objects.writer."""

from types import SimpleNamespace
from typing import cast

from space_map_data.export.objects import writer
from space_map_data.export.wikidata import WikidataEntity
from space_map_data.models.object import Object


def _entity(labels: dict[str, str]) -> WikidataEntity:
    return WikidataEntity(
        labels=labels, descriptions={}, aliases={}, claims={}, sitelinks={}
    )


class _Cache:
    """Stands in for WikidataEntityCache, serving only referenced entities."""

    def __init__(self, entities: dict[str, WikidataEntity]):
        self.entities = entities

    def get_referenced(self, qid: str | None) -> WikidataEntity | None:
        return self.entities.get(qid or "")


def _localized(obj_id: str, lang: str, wd: WikidataEntity, cache: _Cache) -> dict:
    return writer._build_localized(
        cast(Object, SimpleNamespace(id=obj_id, norad_cat_id=None, satcat=None)),
        lang,
        cast(writer.WikidataEntityCache, cache),
        wd,
        {},
        None,
    )


class TestNameEntities:
    """A probe filed against its mission is named by the craft instead."""

    def test_override_replaces_the_label(self):
        cache = _Cache({"Q48485": _entity({"en": "Curiosity"})})
        data = _localized(
            "probe-100265984", "en", _entity({"en": "Mars Science Laboratory"}), cache
        )
        assert data["name"] == "Curiosity"

    def test_override_is_per_language(self):
        cache = _Cache({"Q48485": _entity({"en": "Curiosity", "ja": "キュリオシティ"})})
        data = _localized(
            "probe-100265984",
            "ja",
            _entity({"ja": "マーズ・サイエンス・ラボラトリー"}),
            cache,
        )
        assert data["name"] == "キュリオシティ"

    def test_uncurated_object_keeps_its_own_label(self):
        cache = _Cache({"Q48485": _entity({"en": "Curiosity"})})
        data = _localized(
            "probe-113246208", "en", _entity({"en": "Perseverance"}), cache
        )
        assert data["name"] == "Perseverance"

    def test_missing_substitute_falls_back(self):
        """A referenced entity the download missed must not erase the name."""
        data = _localized(
            "probe-100265984",
            "en",
            _entity({"en": "Mars Science Laboratory"}),
            _Cache({}),
        )
        assert data["name"] == "Mars Science Laboratory"

    def test_curated_ids_are_probe_ids(self):
        for obj_id, qid in writer.NAME_ENTITIES.items():
            assert obj_id.startswith("probe-")
            assert qid.startswith("Q")
