"""Tests for the object entries of the stars with a Wikidata item or a value
from a paper, and of the planets with an item."""

import gzip
from pathlib import Path
from typing import cast

import orjson
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.export.objects import stars
from space_map_data.export.objects.stars import (
    PlanetObject,
    StarObject,
    _read_part,
    available_extrasolar_objects,
    has_description,
    read_extrasolar_objects,
    replace_bundle_entries,
    star_entries,
    star_references,
)
from space_map_data.export.objects.wikipedia import WikipediaSummary
from space_map_data.export.objects.writer import hash_bucket
from space_map_data.export.wikidata import StarEntity, WikidataEntityCache
from space_map_data.extrasolar.registry import Registry, RegistryBusy
from space_map_data.extrasolar.tables import CROSS_ID
from tests.extrasolar.export_registry import (
    Held,
    Node,
    planet,
    star,
    write_registry,
)

ETA_CAR = ("gaia", "dr3", "5350358584482202880")
SMITH_2006 = {
    "short": "Smith 2006",
    "title": (
        "The Structure of the Homunculus. I. Shape and Latitude Dependence from"
        " H2 and [Fe II] Velocity Maps of η Carinae (ApJ 644, 1151)"
    ),
    "url": "https://doi.org/10.1086/503766",
}


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
                    {
                        "en": "Sirius",
                        "fr": "Sirius",
                        "ru": "Сириус",
                        "ja": "HD 48915",
                        "pl": "Syriusz",
                        "de": "Sirius (Stern)",
                    },
                    {"en": "brightest star in the night sky"},
                    {"de": ["Hundsstern"], "pl": ["syriusz", "Psia Gwiazda", "Sirius"]},
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
                StarObject(22137869, "Sirius", "Q1", iau_named=True),
                StarObject(5, "Hamal", "Q2"),
                StarObject(6, "HD 7", "Q3"),
                # A distance from a paper, and no Wikidata item.
                StarObject(7, "η Carinae", None, ETA_CAR),
                # A resolved star system.
                StarObject(9, "Alpha Centauri", "Q4", object_type="multiple_star"),
            ],
            entities,
        )
        # Each star entity is read once.
        assert cast(_Entities, entities).star_reads == ["Q1", "Q2", "Q3", "Q4"]
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
        assert global_data["x-7"] == {
            "id": "x-7",
            "type": "star",
            "name": "η Carinae",
            "references": {"distance": [SMITH_2006]},
        }
        assert global_data["x-9"] == {
            "id": "x-9",
            "type": "multiple_star",
            "name": "Alpha Centauri",
            "cross_refs": {"wikidata_qid": "Q4"},
        }
        assert set(global_data) == {"x-22137869", "x-5", "x-6", "x-7", "x-9"}

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
                "primary_type": "group",
                "primary_id": "sky-canis-major",
            },
            "wikipedia": {"extract": "Sirius is…", "url": "https://en…"},
        }
        assert localized["ru"]["x-22137869"] == {
            "name": "Сириус",
            "instance_of": [{"name": "двойная звезда"}],
            "part_of": [hamal],
            "iau_constellation": {
                "name": "Большой Пёс",
                "primary_type": "group",
                "primary_id": "sky-canis-major",
            },
        }
        assert localized["de"]["x-22137869"] == {
            "aliases": ["Hundsstern"],
            "part_of": [hamal],
        }
        # A link to a star with an entry takes the name of its page.
        assert localized["zh"]["x-22137869"]["part_of"] == [{**hamal, "name": "婁宿三"}]
        # The same label as in English is no name, and a Latin label does not
        # replace an IAU name.
        assert "name" not in localized["fr"]["x-22137869"]
        assert "name" not in localized["ja"]["x-22137869"]
        assert localized["zh"]["x-5"] == {"name": "婁宿三"}
        assert "x-5" not in localized["fr"]
        # No entity downloaded, or no item: a global entry only.
        assert not any("x-6" in entries for entries in localized.values())
        assert not any("x-7" in entries for entries in localized.values())

    def test_a_label_that_the_iau_name_replaces_is_an_alias(self, entries):
        _, localized = entries
        # First, and with the Wikidata aliases once in any case, without the
        # page's name.
        assert localized["pl"]["x-22137869"]["aliases"] == ["Syriusz", "Psia Gwiazda"]
        # Without its disambiguator, the label is the IAU name.
        assert localized["de"]["x-22137869"]["aliases"] == ["Hundsstern"]

    def test_references(self):
        assert star_references(StarObject(7, "η Carinae", "Q1", ETA_CAR)) == {
            "distance": [SMITH_2006]
        }
        assert star_references(StarObject(5, "Hamal", "Q2")) == {}
        # A key that the table no longer has cites nothing.
        assert star_references(StarObject(8, "X", None, ("hip", "2007", "1"))) == {}

    def test_description(self):
        assert has_description({"wikipedia": {"extract": "Sirius is…"}})
        assert not has_description({"wikipedia": {"url": "https://en…"}})
        assert not has_description({"description": "star"})
        assert not has_description(None)


class TestPlanetEntries:
    """Planets take the entries of stars, under their scene ids."""

    @pytest.fixture
    def entries(self, monkeypatch):
        summaries = {
            "Q1": {"en": WikipediaSummary(extract="51 Pegasi b is…", url="https://en…")}
        }
        monkeypatch.setattr(
            stars,
            "load_wikipedia_summaries_for_qid",
            lambda qid: summaries.get(qid, {}),
        )
        monkeypatch.setattr(
            stars,
            "collect_star_images",
            lambda qid: [{"file": "51 Peg b.jpg"}] if qid == "Q1" else None,
        )
        entities = fake_entities(
            {
                # The host star, whose page the planet's part_of links to.
                "Q9": entity({"en": "51 Pegasi"}),
                "Q4": entity({"en": "Kepler-34 AB", "ar": "كبلر-34", "he": "קפלר-34"}),
                "Q1": entity(
                    {
                        "en": "51 Pegasi b",
                        "ja": "ペガスス座51番星b",
                        "ru": "51 Пегаса b",
                        "de": "Dimidium (Exoplanet)",
                        "fr": "Bellérophon (planète)",
                        "es": "Dimídium",
                    },
                    {"en": "exoplanet orbiting 51 Pegasi"},
                    {"en": ["Bellerophon", "NAME Bellerophon", "* 51 Peg b"]},
                    {"P361": items("Q9")},
                ),
                "Q2": entity(
                    {
                        "en": "Kepler-34 b",
                        "de": "Kepler-34b",
                        "ja": "ケプラー34b",
                        # Wikidata gives the name of the star, or a nickname.
                        "pt": "Kepler-34",
                        "fr": "Gliese 34 Ab",
                        "es": "KEPLER-34B",
                        "ru": "Осирис",
                        # Its designation where the star's label is "קפלר-34".
                        "he": "קפלר-34 בי",
                        "ar": "كبلر-34",
                    }
                ),
            },
            sitelinks={"Q1": 20},
        )
        return star_entries(
            [StarObject(9, "51 Peg", "Q9"), StarObject(4, "Kepler-34 AB", "Q4")],
            entities,
            [
                PlanetObject(9, 1, "Dimidium", "Q1", ("51 Peg b",), "b", True),
                PlanetObject(
                    4, 2, "Kepler-34 b", "Q2", ("Kepler-34 b", "GJ 34 A b"), "b"
                ),
            ],
        )

    def test_global(self, entries):
        global_data, _ = entries
        assert global_data["x-9-b-1"] == {
            "id": "x-9-b-1",
            "type": "exoplanet",
            "name": "Dimidium",
            "cross_refs": {"wikidata_qid": "Q1"},
            "sitelinks_count": 20,
            "images": [{"file": "51 Peg b.jpg"}],
        }
        assert set(global_data) == {"x-9", "x-4", "x-9-b-1", "x-4-b-2"}

    def test_localized(self, entries):
        _, localized = entries
        assert localized["en"]["x-9-b-1"] == {
            "description": "exoplanet orbiting 51 Pegasi",
            # Without SIMBAD's prefixes, each once.
            "aliases": ["Bellerophon", "51 Peg b"],
            "part_of": [{"name": "51 Peg", "primary_id": "9", "primary_type": "x"}],
            "wikipedia": {"extract": "51 Pegasi b is…", "url": "https://en…"},
        }

    def test_an_iau_name_stays_in_every_language(self, entries):
        _, localized = entries
        assert "name" not in localized["ja"]["x-9-b-1"]
        assert "name" not in localized["ru"]["x-9-b-1"]

    def test_a_planet_takes_its_hosts_name_and_its_letter(self, entries):
        """A language has a name where it differs from the global one, which
        is the `name` of the planet's system file record."""
        global_data, localized = entries
        assert global_data["x-4-b-2"]["name"] == "Kepler-34 AB b"
        assert "x-4-b-2" not in localized["en"]
        assert localized["ar"]["x-4-b-2"]["name"] == "كبلر-34 b"
        # Its own label names it in no language.
        assert "name" not in localized["ja"]["x-4-b-2"]

    def test_the_catalogue_name_is_an_alias_of_another_name(self, entries):
        _, localized = entries
        assert localized["ar"]["x-4-b-2"]["aliases"] == ["Kepler-34 b"]
        # The same designation, with the pair's letters.
        assert "x-4-b-2" not in localized["en"]

    def test_a_nickname_is_an_alias(self, entries):
        _, localized = entries
        assert localized["ru"]["x-4-b-2"]["aliases"] == ["Осирис"]
        assert localized["ja"]["x-4-b-2"]["aliases"] == ["ケプラー34b"]
        # A name of the star in a script that has no designation key; the
        # planet's own name in that script is no name of its page.
        assert localized["he"]["x-4-b-2"] == {
            "name": "קפלר-34 b",
            "aliases": ["Kepler-34 b", "קפלר-34 בי"],
        }

    def test_an_iau_named_planet_keeps_its_other_labels_as_aliases(self, entries):
        _, localized = entries
        assert localized["ja"]["x-9-b-1"]["aliases"] == ["ペガスス座51番星b"]
        # Without Wikidata's qualifier.
        assert localized["fr"]["x-9-b-1"]["aliases"] == ["Bellérophon"]

    def test_a_label_that_is_its_name_spelled_another_way_is_no_alias(self, entries):
        _, localized = entries
        # Gliese numbers go by GJ too, and a label can name the star.
        for lang in ("de", "es", "fr", "pt"):
            assert "x-4-b-2" not in localized[lang]
        assert "aliases" not in localized["de"]["x-9-b-1"]
        assert "aliases" not in localized["es"]["x-9-b-1"]


class TestReadStarObjects:
    """The IDs with an entry, from the registry."""

    def test_no_registry_gives_none(self, tmp_path, caplog):
        assert available_extrasolar_objects(tmp_path) == ([], [])
        assert "No star or planet entries" in caplog.text

    def test_a_registry_that_an_ingest_holds_fails(self, tmp_path):
        with Registry(tmp_path).writer(), pytest.raises(RegistryBusy):
            available_extrasolar_objects(tmp_path)

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
                ("name_source", pa.string()),
                ("class", pa.string()),
                ("cross_ids", pa.list_(CROSS_ID)),
                ("object", pa.bool_()),
            ]
        )
        pq.write_table(pa.Table.from_pylist(rows, schema), path)
        with pytest.raises(ValueError, match=r"ID 6 has the Wikidata items \['Q10'"):
            _read_part(path)
        pq.write_table(pa.Table.from_pylist(rows[:1], schema), path)
        assert _read_part(path) == [StarObject(5, "Vega", "Q2")]

    def test_a_node_of_a_star_system_takes_its_class_as_its_type(self, tmp_path):
        path = tmp_path / "part.parquet"
        rows = [
            {
                "id": id_,
                "name": name,
                "name_source": source,
                "class": cls,
                "object": True,
                "cross_ids": [item],
            }
            for id_, name, source, cls, item in (
                (5, "Capella", "iau-wgsn", "binary star", self._item("Q1")),
                (6, "Alpha Centauri", "wikidata", "multiple star", self._item("Q2")),
                (7, "Vega", "iau-wgsn", "star", self._item("Q3")),
                (8, "Sirius B", "simbad", "white dwarf", self._item("Q4")),
            )
        ]
        pq.write_table(pa.Table.from_pylist(rows), path)
        found = _read_part(path)
        assert [star.object_type for star in found] == [
            "binary_star",
            "multiple_star",
            "star",
            "star",
        ]
        # The IAU name is kept in every language.
        assert [star.iau_named for star in found] == [True, False, True, False]

    @staticmethod
    def _item(qid: str) -> dict:
        return {"catalogue": "wikidata", "release": "qid", "catalogue_id": qid}

    def test_an_id_with_a_literature_key(self, tmp_path):
        path = tmp_path / "part.parquet"
        key = {
            "catalogue": "literature",
            "release": "star",
            "catalogue_id": "gaia/dr3/5350358584482202880",
        }
        item = {"catalogue": "wikidata", "release": "qid", "catalogue_id": "Q9"}
        gaia = {"catalogue": "gaia", "release": "dr3", "catalogue_id": "1"}
        rows = [
            {"id": 7, "name": "η Car", "cross_ids": [gaia, key], "object": True},
            {"id": 8, "name": "Vega", "cross_ids": [key, item], "object": True},
            {"id": 9, "name": "Deneb", "cross_ids": [gaia], "object": True},
        ]
        schema = pa.schema(
            [
                ("id", pa.int64()),
                ("name", pa.string()),
                ("name_source", pa.string()),
                ("class", pa.string()),
                ("cross_ids", pa.list_(CROSS_ID)),
                ("object", pa.bool_()),
            ]
        )
        pq.write_table(pa.Table.from_pylist(rows, schema), path)
        with pytest.raises(ValueError, match="ID 9 has the Wikidata items"):
            _read_part(path)
        pq.write_table(pa.Table.from_pylist(rows[:2], schema), path)
        assert _read_part(path) == [
            StarObject(7, "η Car", None, ETA_CAR),
            StarObject(8, "Vega", "Q9", ETA_CAR),
        ]

    def test_a_held_star_with_an_item_is_a_star(self, tmp_path):
        """A held star has an entry as a star has: by its Wikidata item."""
        held = {"A": Held("Kepler-16 A", qid="Q5"), "B": Held("Kepler-16 B")}
        systems = [Node((("held", None, "A"), ("held", None, "B")), 0, held=held)]
        built = write_registry(tmp_path / "reg", [star(10.0, 20.0)], systems=systems)
        stars, _ = read_extrasolar_objects(built.root)
        assert stars == [StarObject(built.held[0, "A"], "Kepler-16 A", "Q5")]


class TestReadPlanetObjects:
    """The planets with an entry: those whose row holds a Wikidata QID."""

    def test_a_qid_in_the_cross_ids(self, tmp_path):
        archive = {
            "catalogue": "nasa-exoplanet-archive",
            "release": "pscomppars",
            "catalogue_id": "3.1",
        }
        item = {"catalogue": "wikidata", "release": "qid", "catalogue_id": "Q1"}
        built = write_registry(
            tmp_path / "registry",
            [star(10, 20, 50, name="51 Peg")],
            planets=[
                planet(
                    0,
                    1,
                    name="Dimidium",
                    name_source="iau-nameexoworlds",
                    designation="51 Peg b",
                    aliases=["Dimidium", "51 Peg b"],
                    cross_ids=[archive, item],
                ),
                planet(0, 2, letter="c"),
            ],
        )
        assert read_extrasolar_objects(built.root)[1] == [
            PlanetObject(
                built.ids[0], 1, "Dimidium", "Q1", ("51 Peg b", "Dimidium"), "b", True
            )
        ]

    def test_a_status_and_a_repeated_letter(self, tmp_path):
        """A planet with no entry counts too: its letter is on another page."""
        item = {"catalogue": "wikidata", "release": "qid", "catalogue_id": "Q1"}
        built = write_registry(
            tmp_path / "registry",
            [star(10, 20, 50, name="GJ 229")],
            planets=[
                planet(0, 1, status="controversial", cross_ids=[item]),
                planet(0, 2, letter="c", cross_ids=[item]),
                planet(0, 3, letter="c"),
                planet(0, 4, letter="d", cross_ids=[item]),
            ],
        )
        entries = read_extrasolar_objects(built.root)[1]
        assert [(p.number, p.controversial, p.letter_repeated) for p in entries] == [
            (1, True, False),
            (2, False, True),
            (4, False, False),
        ]


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
            stars,
            "read_extrasolar_objects",
            lambda: ([StarObject(7, "Vega", "Q9")], []),
        )
        monkeypatch.setattr(
            stars,
            "WikidataEntityCache",
            lambda: fake_entities({"Q9": entity({"en": "Vega", "ru": "Вега"})}),
        )
        monkeypatch.setattr(stars, "load_wikipedia_summaries_for_qid", lambda qid: {})
        monkeypatch.setattr(stars, "collect_star_images", lambda qid: None)
        stars.export_star_objects_only(out, tmp_path / "extrasolar")
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
