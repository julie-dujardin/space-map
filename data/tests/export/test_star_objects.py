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
from space_map_data.export.wikidata import StarEntity, WikidataEntityCache
from space_map_data.extrasolar.registry import Registry, RegistryBusy
from space_map_data.extrasolar.tables import CROSS_ID


def entity(
    labels: dict,
    descriptions: dict | None = None,
    aliases: dict | None = None,
    claims: dict | None = None,
    sitelinks: dict | None = None,
):
    return {
        "labels": labels,
        "descriptions": descriptions or {},
        "aliases": aliases or {},
        "claims": claims or {},
        "sitelinks": sitelinks or {},
    }


def statement(value) -> dict:
    return {"rank": "normal", "mainsnak": {"datavalue": {"value": value}}}


def items(*qids: str) -> list[dict]:
    return [statement({"id": qid}) for qid in qids]


class _Entities:
    def __init__(
        self,
        by_qid: dict,
        referenced: dict | None = None,
        sitelinks: dict | None = None,
    ) -> None:
        self.by_qid = by_qid
        self.referenced = referenced or {}
        self.sitelinks = sitelinks or {}
        self.star_reads: list[str] = []

    def get_star_entity(self, qid):
        self.star_reads.append(qid)
        found = self.by_qid.get(qid)
        return None if found is None else StarEntity(found, self.sitelinks.get(qid, 0))

    def get_referenced(self, qid):
        return self.referenced.get(qid)


def fake_entities(
    by_qid: dict, referenced: dict | None = None, sitelinks: dict | None = None
) -> WikidataEntityCache:
    return cast(WikidataEntityCache, _Entities(by_qid, referenced, sitelinks))


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
        monkeypatch.setattr(
            stars,
            "collect_star_images",
            lambda qid: [{"file": "Sirius.jpg"}] if qid == "Q1" else None,
        )
        claims = {
            # Binary star; infrared source; A-type main-sequence star.
            "P31": items("Q50053", "Q67206691", "Q471805"),
            "P59": items("Q10538"),
            "P361": items("Q2"),
            "P575": [
                statement(
                    {
                        "time": "+1862-01-31T00:00:00Z",
                        "precision": 11,
                        "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
                    }
                )
            ],
        }
        referenced = {
            "Q50053": entity(
                {"en": "binary star", "ru": "двойная звезда"},
                sitelinks={"en": "Binary star"},
            ),
            # A subclass of A-type star, a spectral class.
            "Q471805": entity(
                {"en": "A-type main sequence star"},
                claims={"P279": items("Q14745284")},
            ),
            "Q10538": entity(
                {"en": "Canis Major", "ru": "Большой Пёс"},
                sitelinks={"en": "Canis Major"},
            ),
        }
        entities = fake_entities(
            {
                "Q1": entity(
                    {"en": "Sirius", "fr": "Sirius", "ru": "Сириус", "ja": "HD 48915"},
                    {"en": "brightest star in the night sky"},
                    {"de": ["Hundsstern"]},
                    claims,
                ),
                # Wikidata calls Hamal by its Bayer designation.
                "Q2": entity(
                    {"en": "Alpha Arietis", "fr": "Alpha Arietis", "zh": "婁宿三"}
                ),
            },
            referenced,
            {"Q1": 120},
        )
        found = star_entries(
            [
                StarObject(22137869, "Sirius", "Q1"),
                StarObject(5, "Hamal", "Q2"),
                StarObject(6, "HD 7", "Q3"),
            ],
            entities,
        )
        # Each star entity is read once.
        assert cast(_Entities, entities).star_reads == ["Q1", "Q2", "Q3"]
        return found

    def test_global(self, entries):
        global_data, _ = entries
        assert global_data["x-22137869"] == {
            "id": "x-22137869",
            "type": "star",
            "name": "Sirius",
            "cross_refs": {"wikidata_qid": "Q1"},
            "sitelinks_count": 120,
            "images": [{"file": "Sirius.jpg"}],
            "wikidata": {"discovery_date": ["+1862-01-31T00:00:00Z"]},
        }
        assert global_data["x-5"] == {
            "id": "x-5",
            "type": "star",
            "name": "Hamal",
            "cross_refs": {"wikidata_qid": "Q2"},
        }
        assert set(global_data) == {"x-22137869", "x-5", "x-6"}

    def test_localized(self, entries):
        _, localized = entries
        hamal = {"name": "Hamal", "primary_id": "5", "primary_type": "x"}
        assert localized["en"]["x-22137869"] == {
            "description": "brightest star in the night sky",
            "instance_of": [
                {
                    "name": "binary star",
                    "wikipedia": "https://en.wikipedia.org/wiki/Binary%20star",
                }
            ],
            "part_of": [hamal],
            "iau_constellation": {
                "name": "Canis Major",
                "wikipedia": "https://en.wikipedia.org/wiki/Canis%20Major",
            },
            "wikipedia": {"extract": "Sirius is…", "url": "https://en…"},
        }
        assert localized["ru"]["x-22137869"] == {
            "name": "Сириус",
            "instance_of": [{"name": "двойная звезда"}],
            "part_of": [hamal],
            "iau_constellation": {"name": "Большой Пёс"},
        }
        assert localized["de"]["x-22137869"] == {
            "aliases": ["Hundsstern"],
            "part_of": [hamal],
        }
        # A link to a star with an entry takes the name of its page.
        assert localized["zh"]["x-22137869"]["part_of"] == [{**hamal, "name": "婁宿三"}]
        # The same label as in English, or a catalogue number, is no name.
        assert "name" not in localized["fr"]["x-22137869"]
        assert "name" not in localized["ja"]["x-22137869"]
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
        monkeypatch.setattr(stars, "collect_star_images", lambda qid: None)
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
