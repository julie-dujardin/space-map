"""Tests for the search documents of planets and their host stars."""

import gzip
import json

import pytest

from space_map_data.export.extrasolar import planets
from space_map_data.export.extrasolar.build import export_extrasolar
from space_map_data.extrasolar.systems import drawn
from space_map_data.search.indices import objects
from space_map_data.search.indices.catalog import CATALOG_INDEX
from space_map_data.search.indices.extrasolar import (
    build_extrasolar_documents,
    designations,
    host_document,
    planet_document,
)
from tests.extrasolar.export_registry import Node, planet, write_registry
from tests.extrasolar.test_export_planets import PLANETS, STARS
from tests.extrasolar.test_export_systems import (
    ALPHA_CEN,
    KEPLER,
    KEPLER_16,
    KEPLER_PAIR,
    KEPLER_STAR,
    PAIR,
    SYSTEMS,
    _stars,
)


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
    """A host with an entry keeps main's star document, with or without a
    description."""

    def _write(self, tmp_path, star: str, english: dict) -> None:
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
            "en": {star: english},
            "ru": {star: {"name": "Альфа"}},
        }
        for tier, entries in bundles.items():
            directory = tmp_path / "export" / "v1" / "objects" / tier
            directory.mkdir(parents=True)
            (directory / "0.json.gz").write_bytes(
                gzip.compress(json.dumps(entries).encode())
            )

    def test_without_a_description(self, exported, tmp_path, monkeypatch):
        monkeypatch.setattr(objects, "LANGUAGES", ("en", "ru"))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        built, out = exported
        star = f"x-{built.ids[0]}"
        self._write(tmp_path, star, {"aliases": ["HD 1"], "description": "a star"})

        docs = list(CATALOG_INDEX.build_documents(tmp_path / "export", out))
        alpha = [doc for doc in docs if doc["id"] == star]
        assert len(alpha) == 1
        assert alpha[0]["name"] == "Alpha"
        assert alpha[0]["name_ru"] == "Альфа"
        assert alpha[0]["sitelinks_count"] == 40
        assert alpha[0]["object"]["planets"] == 2

    def test_the_planet_facts_go_on_the_star_document(
        self, exported, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(objects, "LANGUAGES", ("en", "ru"))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        built, out = exported
        star = f"x-{built.ids[0]}"
        english = {
            "aliases": ["HD 1"],
            "description": "a star",
            "wikipedia": {"extract": "Alpha is a star."},
        }
        self._write(tmp_path, star, english)

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


class TestPlanetWithAnEntry:
    """A planet with an entry keeps its planet document, with the entry's
    names on it."""

    def test_the_entry_goes_on_the_planet_document(
        self, exported, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(objects, "LANGUAGES", ("en", "ru"))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        built, out = exported
        lucky = f"x-{built.ids[0]}-b-2"
        # The extrasolar export does not serve this one.
        gone = f"x-{built.ids[0]}-b-9"
        bundles = {
            "__global__": {
                key: {"id": key, "type": "exoplanet", "name": "Lucky"}
                | ({"sitelinks_count": 30} if key == lucky else {})
                for key in (lucky, gone)
            },
            "en": {
                key: {
                    "aliases": ["Planet Lucky"],
                    "description": "a planet",
                    "wikipedia": {"extract": "Lucky is a planet."},
                }
                for key in (lucky, gone)
            },
            "ru": {lucky: {"name": "Счастливая"}},
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
        assert gone not in keys
        doc = dict(zip(keys, docs))[lucky]
        assert doc["kind"] == "planet"
        # The names come from the system file, which has them for every planet.
        assert doc["name"] == "Lucky"
        assert "name_ru" not in doc
        assert doc["description_en"] == "a planet"
        assert doc["sitelinks_count"] == 30
        assert doc["planet"]["aliases_en"] == ["Planet Lucky"]
        assert doc["planet"]["designation"] == "Planet 0 2"


class TestSystems:
    """The systems index of the export: Kepler-16, a point that hosts a
    planet and holds A and B, and the pair of SYSTEMS with an orbit."""

    @pytest.fixture
    def kepler(self, tmp_path):
        planets = [planet(KEPLER_STAR, 1, binary_type="P-type")]
        orbit = drawn.scene(KEPLER_PAIR | {"ra": 120.0, "dec": -30.0}, 10.0)
        pair = Node(SYSTEMS[PAIR].members, orbit=orbit, name="The Pair")
        systems = [*SYSTEMS[:PAIR], pair, KEPLER_16]
        built = write_registry(
            tmp_path / "reg", _stars(), systems=systems, planets=planets
        )
        out = tmp_path / "out"
        export_extrasolar(built.root, out, workers=1, cultures_dir=tmp_path / "none")
        return built, out

    def _entries(self, tmp_path, entries: dict[str, dict]) -> None:
        """Main's object entries: `entries` maps a key to its English entry."""
        bundles = {
            "__global__": {
                key: {"id": key, "type": "binary_star", "name": "Entry"}
                for key in entries
            },
            "en": entries,
        }
        for tier, rows in bundles.items():
            directory = tmp_path / "export" / "v1" / "objects" / tier
            directory.mkdir(parents=True)
            (directory / "0.json.gz").write_bytes(
                gzip.compress(json.dumps(rows).encode())
            )

    def test_the_index_makes_no_document(self, kepler):
        """With no entries, only the host has a document, with the system's
        facts on it."""
        built, out = kepler
        docs = {doc["id"]: doc for doc in build_extrasolar_documents(out)}
        point = f"x-{built.nodes[KEPLER]}"
        assert docs[point]["name"] == "Kepler-16"
        assert docs[point]["object"] == {
            "id": point,
            "type": "binary_star",
            "extrasolar": True,
            "planets": 1,
            "stars": 2,
            "designations": [f"Gaia DR3 {built.ids[KEPLER_STAR] * 7}"],
        }
        assert f"x-{built.held[KEPLER, 'A']}" not in docs
        assert f"x-{built.held[KEPLER, 'B']}" not in docs
        assert f"x-{built.nodes[PAIR]}" not in docs
        assert f"x-{built.nodes[ALPHA_CEN]}" not in docs

    def test_an_entry_with_no_extract_is_left_out(self, kepler, tmp_path, monkeypatch):
        monkeypatch.setattr(objects, "LANGUAGES", ("en",))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        built, out = kepler
        key = f"x-{built.nodes[PAIR]}"
        self._entries(tmp_path, {key: {"aliases": ["The Pair"]}})
        docs = list(CATALOG_INDEX.build_documents(tmp_path / "export", out))
        assert key not in {doc["id"] for doc in docs}

    def test_an_entry_with_an_extract_takes_the_facts(
        self, kepler, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(objects, "LANGUAGES", ("en",))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        built, out = kepler
        pair = f"x-{built.nodes[PAIR]}"
        held = f"x-{built.held[KEPLER, 'A']}"
        extract = {"wikipedia": {"extract": "A pair of stars."}}
        self._entries(tmp_path, {pair: extract, held: extract})
        docs = list(CATALOG_INDEX.build_documents(tmp_path / "export", out))
        keys = [doc["id"] for doc in docs]
        assert len(keys) == len(set(keys))
        by_key = dict(zip(keys, docs))
        assert by_key[pair]["object"]["stars"] == 2
        assert by_key[pair]["object"]["type"] == "binary_star"
        point = f"x-{built.nodes[KEPLER]}"
        assert by_key[held]["object"]["system_id"] == point
        assert by_key[held]["object"]["system_name"] == "Kepler-16"
        assert f"x-{built.held[KEPLER, 'B']}" not in by_key

    def test_an_export_with_no_systems_index(self, exported):
        _, out = exported
        path = out / "v1" / "x" / "metadata.json"
        metadata = json.loads(path.read_text())
        del metadata["systems"]
        path.write_text(json.dumps(metadata))
        docs = list(build_extrasolar_documents(out))
        assert {doc["kind"] for doc in docs} == {"object", "planet"}


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


class TestNames:
    """The names of the pages, from the `names` of the system file."""

    @staticmethod
    def _host() -> dict:
        return {
            "id": 7,
            "class": "star",
            "planets": [1],
            "name": "alf Cen",
            "names": {"ja": "ケンタウルス座α星"},
            "catalogue_name": None,
            "cross_ids": [],
        }

    def test_a_host_has_the_names_of_its_page(self):
        doc = host_document(self._host())
        assert doc["name"] == "alf Cen"
        assert doc["name_ja"] == "ケンタウルス座α星"

    def test_a_planet_has_the_names_of_its_page_and_of_its_host(self):
        planet = {
            "host": 7,
            "number": 1,
            "name": "alf Cen b",
            "names": {"ja": "ケンタウルス座α星 b"},
            "designation": "alf Cen b",
            "class": "planet",
            "status": "confirmed",
            "aliases": [],
            "values": {},
        }
        doc = planet_document(planet, 7, self._host())
        assert doc["name"] == "alf Cen b"
        assert doc["name_ja"] == "ケンタウルス座α星 b"
        assert "name_fr" not in doc
        assert doc["planet"]["host_name"] == "alf Cen"
        assert doc["planet"]["host_name_ja"] == "ケンタウルス座α星"
