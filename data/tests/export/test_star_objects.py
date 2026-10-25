"""Tests for the object entries of the stars with a Wikidata item."""

import gzip
from pathlib import Path
from typing import cast

import orjson
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.export.objects import stars
from space_map_data.export.objects.stars import (
    StarObject,
    _read_part,
    available_star_objects,
    replace_bundle_entries,
    star_entries,
)
from space_map_data.export.objects.wikipedia import WikipediaSummary
from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.wikidata import WikidataEntityCache
from space_map_data.extrasolar.registry import Registry, RegistryBusy
from space_map_data.extrasolar.tables import CROSS_ID


def entity(labels: dict, descriptions: dict | None = None, aliases: dict | None = None):
    return {
        "labels": labels,
        "descriptions": descriptions or {},
        "aliases": aliases or {},
        "claims": {},
        "sitelinks": {},
    }


class _Entities:
    def __init__(self, by_qid: dict) -> None:
        self.by_qid = by_qid

    def get_star_entity(self, qid):
        return self.by_qid.get(qid)


def fake_entities(by_qid: dict) -> WikidataEntityCache:
    return cast(WikidataEntityCache, _Entities(by_qid))


def bundle(path: Path) -> dict:
    return orjson.loads(gzip.decompress(path.read_bytes()))


class TestStarEntries:
    """Names, text and articles of each star in each language."""

    @pytest.fixture
    def entries(self, monkeypatch):
        summaries = {
            "Q1": {"en": WikipediaSummary(extract="Sirius is…", url="https://en…")},
        }
        monkeypatch.setattr(
            stars,
            "load_wikipedia_summaries_for_qid",
            lambda qid: summaries.get(qid, {}),
        )
        entities = fake_entities(
            {
                "Q1": entity(
                    {"en": "Sirius", "fr": "Sirius", "ru": "Сириус", "ja": "HD 48915"},
                    {"en": "brightest star in the night sky"},
                    {"de": ["Hundsstern"]},
                ),
                # Wikidata calls Hamal by its Bayer designation.
                "Q2": entity(
                    {"en": "Alpha Arietis", "fr": "Alpha Arietis", "zh": "婁宿三"}
                ),
            }
        )
        return star_entries(
            [
                StarObject(22137869, "Sirius", "Q1"),
                StarObject(5, "Hamal", "Q2"),
                StarObject(6, "HD 7", "Q3"),
            ],
            entities,
        )

    def test_global(self, entries):
        global_data, _ = entries
        assert global_data["x-22137869"] == {
            "id": "x-22137869",
            "type": "star",
            "name": "Sirius",
            "cross_refs": {"wikidata_qid": "Q1"},
        }
        assert set(global_data) == {"x-22137869", "x-5", "x-6"}

    def test_localized(self, entries):
        _, localized = entries
        assert localized["en"]["x-22137869"] == {
            "description": "brightest star in the night sky",
            "wikipedia": {"extract": "Sirius is…", "url": "https://en…"},
        }
        assert localized["ru"]["x-22137869"] == {"name": "Сириус"}
        assert localized["de"]["x-22137869"] == {"aliases": ["Hundsstern"]}
        # The same label as in English, or a catalogue number, is no name.
        assert "x-22137869" not in localized["fr"]
        assert "x-22137869" not in localized["ja"]
        assert localized["zh"]["x-5"] == {"name": "婁宿三"}
        assert "x-5" not in localized["fr"]
        # No entity downloaded: a global entry only.
        assert not any("x-6" in entries for entries in localized.values())


class TestReadStarObjects:
    """The IDs with an entry, from the registry."""

    def test_no_registry_gives_none(self, tmp_path, caplog):
        assert available_star_objects(tmp_path) == []
        assert "No star entries" in caplog.text

    def test_a_registry_that_an_ingest_holds_fails(self, tmp_path):
        with Registry(tmp_path).writer(), pytest.raises(RegistryBusy):
            available_star_objects(tmp_path)

    def test_an_id_with_two_items_fails(self, tmp_path):
        path = tmp_path / "part.parquet"
        qids = [
            {"catalogue": "wikidata", "release": "qid", "catalogue_id": q}
            for q in ("Q10", "Q2")
        ]
        rows = [
            {"id": 5, "name": "Vega", "cross_ids": qids[1:], "object": True},
            {"id": 6, "name": "Deneb", "cross_ids": qids, "object": True},
        ]
        schema = pa.schema(
            [
                ("id", pa.int64()),
                ("name", pa.string()),
                ("cross_ids", pa.list_(CROSS_ID)),
                ("object", pa.bool_()),
            ]
        )
        pq.write_table(pa.Table.from_pylist(rows, schema), path)
        with pytest.raises(ValueError, match=r"ID 6 has the Wikidata items \['Q10'"):
            _read_part(path)
        pq.write_table(pa.Table.from_pylist(rows[:1], schema), path)
        assert _read_part(path) == [StarObject(5, "Vega", "Q2")]


class TestReplaceBundleEntries:
    """The star entries of written bundles, replaced in place."""

    def test_replace(self, tmp_path):
        directory = tmp_path / "objects" / "__global__"
        directory.mkdir(parents=True)
        n = 3
        old = {
            "naif-399": {"name": "Earth"},
            "x-1": {"name": "Old"},
            "x-2": {"name": "Gone"},
        }
        for bucket in range(n):
            entries = {k: v for k, v in old.items() if hash_bucket(k, n) == bucket}
            (directory / f"{bucket}.json.gz").write_bytes(
                gzip.compress(orjson.dumps(entries))
            )
        changed = replace_bundle_entries(
            directory, n, "x-", {"x-1": {"name": "New"}, "x-3": {"name": "Added"}}
        )
        merged = {}
        for bucket in range(n):
            entries = bundle(directory / f"{bucket}.json.gz")
            assert all(hash_bucket(k, n) == bucket for k in entries)
            merged |= entries
        assert merged == {
            "naif-399": {"name": "Earth"},
            "x-1": {"name": "New"},
            "x-3": {"name": "Added"},
        }
        assert 1 <= changed <= n
        assert (
            replace_bundle_entries(
                directory, n, "x-", {"x-1": {"name": "New"}, "x-3": {"name": "Added"}}
            )
            == 0
        )

    def test_no_bundles_for_entries_fails(self, tmp_path):
        with pytest.raises(ValueError, match="no bundles"):
            replace_bundle_entries(tmp_path, 0, "x-", {"x-1": {}})


class TestOnlyStarObjects:
    """`--only star-objects` against a written export."""

    def test_rewrites_the_tiers_and_the_token(self, tmp_path, monkeypatch):
        out = tmp_path / "v1"
        for tier in ("__global__", "en", "ru"):
            (out / "objects" / tier).mkdir(parents=True)
            (out / "objects" / tier / "0.json.gz").write_bytes(gzip.compress(b"{}"))
        counts = {"global": 1, "en": 1, "ru": 1}
        metadata = {"object_bundles": counts, "versions": {"objects": "old"}}
        (out / "metadata.json").write_bytes(orjson.dumps(metadata))
        monkeypatch.setattr(stars, "LANGUAGES", ("en", "ru"))
        monkeypatch.setattr(
            stars, "read_star_objects", lambda: [StarObject(7, "Vega", "Q9")]
        )
        monkeypatch.setattr(
            stars,
            "WikidataEntityCache",
            lambda: fake_entities({"Q9": entity({"en": "Vega", "ru": "Вега"})}),
        )
        monkeypatch.setattr(stars, "load_wikipedia_summaries_for_qid", lambda qid: {})
        stars.export_star_objects_only(out)
        assert (
            bundle(out / "objects" / "__global__" / "0.json.gz")["x-7"]["name"]
            == "Vega"
        )
        assert bundle(out / "objects" / "ru" / "0.json.gz") == {"x-7": {"name": "Вега"}}
        assert bundle(out / "objects" / "en" / "0.json.gz") == {}
        assert (
            orjson.loads((out / "metadata.json").read_bytes())["versions"]["objects"]
            != "old"
        )
