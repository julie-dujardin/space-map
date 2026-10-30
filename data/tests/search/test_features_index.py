"""Tests for the surface-feature search documents."""

import gzip
import json
from pathlib import Path

from space_map_data.export.nomenclature.writer import (
    write_nomenclature_labels,
    write_nomenclature_positions,
)
from space_map_data.models.feature import Feature
from space_map_data.search.indices.features import build_feature_documents
from tests.conftest import EntityStub, labelled

TRANQUILLITATIS = Feature(
    feature_id=1,
    object_id="naif-301",
    name="Mare Tranquillitatis",
    target="moon",
    center_lat=8.35,
    center_lon=30.83,
    diameter=873.0,
    feature_type_code="ME",
    wikidata_qid="Q1",
)


def _export(root: Path, aliases: dict[str, list[str]]) -> None:
    out = root / "v1"
    by_body = {"naif-301": [TRANQUILLITATIS]}
    entities = EntityStub({"Q1": labelled({"fr": "Mer de la Tranquillité"})})
    write_nomenclature_positions(out, by_body)
    write_nomenclature_labels(out, by_body, entities)
    for lang, names in aliases.items():
        directory = out / "nomenclature" / "details" / lang
        directory.mkdir(parents=True)
        entry = {"naif-301:1": {"aliases": names}}
        (directory / "0.json.gz").write_bytes(gzip.compress(json.dumps(entry).encode()))


class TestFeatureDocuments:
    """One document per feature, with its names in every language."""

    def test_a_label_that_the_iau_name_replaces_stays_findable(self, tmp_path):
        _export(tmp_path, {"fr": ["Mer de la Tranquillité"]})
        (doc,) = build_feature_documents(tmp_path)
        assert doc["name_fr"] == "Mare Tranquillitatis"
        assert doc["feature"]["aliases_fr"] == ["Mer de la Tranquillité"]
        assert "aliases_de" not in doc["feature"]
