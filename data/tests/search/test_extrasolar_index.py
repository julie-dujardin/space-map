"""Tests for the search documents of planets and their host stars."""

import gzip
import json

import pytest

from space_map_data.export.extrasolar import planets
from space_map_data.export.extrasolar.build import export_extrasolar
from space_map_data.search.indices import objects
from space_map_data.search.indices.catalog import CATALOG_INDEX
from space_map_data.search.indices.extrasolar import (
    build_extrasolar_documents,
    designations,
)
from tests.extrasolar.export_registry import write_registry
from tests.extrasolar.test_export_planets import PLANETS, STARS


@pytest.fixture
def exported(tmp_path):
    built = write_registry(tmp_path / "reg", STARS, planets=PLANETS)
    export_extrasolar(
        built.root, tmp_path / "out", workers=1, cultures_dir=tmp_path / "none"
    )
    return built, tmp_path / "out"


class TestExtrasolarDocuments:
    """`build_extrasolar_documents` reads the planet files of the export."""

    def test_every_host_and_planet(self, exported):
        built, out = exported
        docs = {doc["id"]: doc for doc in build_extrasolar_documents(out)}
        hosts = [f"x-{id_}" for id_ in built.ids[:5]]
        planet_keys = [f"x-{built.ids[p['_host']]}-b-{p['number']}" for p in PLANETS]
        assert sorted(docs) == sorted(hosts + planet_keys)
        assert f"x-{built.ids[5]}" not in docs

    def test_a_host_document(self, exported):
        built, out = exported
        docs = {doc["id"]: doc for doc in build_extrasolar_documents(out)}
        host = docs[f"x-{built.ids[0]}"]
        assert host["kind"] == "object"
        assert host["name"] == "Host A"
        assert host["object"]["id"] == f"x-{built.ids[0]}"
        assert host["object"]["type"] == "star"
        assert host["object"]["extrasolar"] is True
        assert host["object"]["planets"] == 2
        assert host["object"]["designations"] == [
            "HD 1",
            f"Gaia DR3 {built.ids[0] * 7}",
        ]

    def test_a_planet_document(self, exported):
        built, out = exported
        docs = {doc["id"]: doc for doc in build_extrasolar_documents(out)}
        lucky = docs[f"x-{built.ids[0]}-b-2"]
        assert lucky["kind"] == "planet"
        assert lucky["name"] == "Lucky"
        assert lucky["planet"] == {
            "host_id": f"x-{built.ids[0]}",
            "number": 2,
            "system_id": f"x-{built.ids[0]}",
            "host_name": "Host A",
            "designation": "Planet 0 2",
            "class": "planet",
            "status": "confirmed",
            "aliases": ["Planet 0 2"],
            "discovery_year": 2000,
            "discovery_method": "Imaging",
        }
        companion = docs[f"x-{built.ids[4]}-b-1"]["planet"]
        assert companion["host_id"] == f"x-{built.ids[4]}"
        assert companion["system_id"] == f"x-{built.ids[0]}"
        assert companion["host_name"] == "Host A B"

    def test_a_file_of_another_export_stops_the_build(self, exported):
        built, out = exported
        path = out / "v1" / "x" / planets.system_path(built.ids[0])
        content = json.loads(gzip.decompress(path.read_bytes()))
        content["token"] = "f" * 16
        path.write_bytes(gzip.compress(json.dumps(content).encode()))
        with pytest.raises(ValueError, match="token"):
            list(build_extrasolar_documents(out))

    def test_no_export(self, tmp_path):
        assert list(build_extrasolar_documents(tmp_path)) == []

    def test_the_catalog_takes_them(self, exported, tmp_path):
        _, out = exported
        docs = list(CATALOG_INDEX.build_documents(tmp_path / "no-export", out))
        assert {doc["kind"] for doc in docs} == {"object", "planet"}
        keys = [doc["id"] for doc in docs]
        assert len(keys) == len(set(keys))

    def test_keys_are_meili_keys(self, exported):
        _, out = exported
        for doc in build_extrasolar_documents(out):
            assert all(c.isalnum() or c in "-_" for c in doc["id"]), doc["id"]


class TestHostWithAnEntry:
    """A host that main indexes as a star with an entry keeps that document."""

    def test_the_planet_facts_go_on_the_star_document(
        self, exported, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(objects, "LANGUAGES", ("en", "ru"))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        built, out = exported
        star = f"x-{built.ids[0]}"
        bundles = {
            "__global__": {
                star: {
                    "id": star,
                    "type": "star",
                    "name": "Alpha",
                    "sitelinks_count": 40,
                    "cross_refs": {"wikidata_qid": "Q1"},
                },
            },
            "en": {star: {"aliases": ["HD 1"], "description": "a star"}},
            "ru": {star: {"name": "Альфа"}},
        }
        for tier, entries in bundles.items():
            directory = tmp_path / "export" / "v1" / "objects" / tier
            directory.mkdir(parents=True)
            (directory / "0.json.gz").write_bytes(
                gzip.compress(json.dumps(entries).encode())
            )

        docs = list(CATALOG_INDEX.build_documents(tmp_path / "export", out))
        keys = [doc["id"] for doc in docs]
        assert len(keys) == len(set(keys))
        by_key = dict(zip(keys, docs))
        alpha = by_key[star]
        assert alpha["name"] == "Alpha"
        assert alpha["name_ru"] == "Альфа"
        assert alpha["description_en"] == "a star"
        assert alpha["sitelinks_count"] == 40
        assert alpha["object"] == {
            "id": star,
            "type": "star",
            "extrasolar": True,
            "planets": 2,
            "designations": ["HD 1", f"Gaia DR3 {built.ids[0] * 7}"],
            "aliases_en": ["HD 1"],
        }
        # A host with no entry keeps its own document.
        lit = by_key[f"x-{built.ids[1]}"]
        assert lit["name"] == "Lit B"
        assert lit["object"]["extrasolar"] is True
        assert lit["object"]["planets"] == 1
        assert "sitelinks_count" not in lit


class TestDesignations:
    def test_names_and_numbers(self):
        host = {
            "catalogue_name": "sig Per",
            "cross_ids": [
                {"catalogue": "gaia", "release": "dr3", "catalogue_id": "42"},
                {"catalogue": "hip", "release": "2007", "catalogue_id": "7"},
                {"catalogue": "hd", "release": "1949", "catalogue_id": "9"},
                {"catalogue": "iau", "release": "wgsn", "catalogue_id": "Name"},
                {
                    "catalogue": "nasa-exoplanet-archive",
                    "release": "pscomppars",
                    "catalogue_id": "2.58355",
                },
                {
                    "catalogue": "exoplanet-eu",
                    "release": "catalog",
                    "catalogue_id": "sig Per",
                },
            ],
        }
        assert designations(host) == ["sig Per", "Gaia DR3 42", "HIP 7", "HD 9", "Name"]
