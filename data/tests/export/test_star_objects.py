"""Tests for the object entries of the stars with a Wikidata item or a value
from a paper, of the galaxies of the galaxy list, and of the planets with an
item."""

import gzip
from pathlib import Path
from typing import cast

import orjson
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from space_map_data.constants.galaxies import literature as galaxy_literature
from space_map_data.constants.stars.literature import REFERENCES
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
    star_facts,
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
    galaxy,
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
            homes={"sky-canis-major": {"culture": "modern_iau", "figure": "CMa"}},
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
                "primary_id": "culture-modern_iau",
                "secondary_type": "figure",
                "secondary_id": "CMa",
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
                "primary_id": "culture-modern_iau",
                "secondary_type": "figure",
                "secondary_id": "CMa",
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
        # One work can give two values.
        uy_sct = ("gaia", "dr3", "4152993273702130432")
        arroyo_torres = [REFERENCES["arroyo_torres_2013"]._asdict()]
        uy_scuti = StarObject(9, "UY Scuti", "Q3", uy_sct, papers=("mass",))
        assert star_references(uy_scuti) == {
            "paper_radius": arroyo_torres,
            "paper_mass": arroyo_torres,
        }
        # A measured value that the record does not hold is not cited.
        assert star_references(StarObject(9, "UY Scuti", "Q3", uy_sct)) == {
            "paper_radius": arroyo_torres
        }
        alnilam = star_references(
            StarObject(10, "Alnilam", "Q4", ("hip", "2007", "26311"), papers=("mass",))
        )
        assert alnilam["distance"] == alnilam["paper_mass"]
        assert alnilam["paper_mass"][0]["short"] == "Oplištilová et al. 2025"
        # A key that the table no longer has cites nothing.
        assert star_references(StarObject(8, "X", None, ("hip", "2007", "1"))) == {}

    def test_a_white_dwarf_of_the_sample_cites_it(self):
        """A measured value of a star with no paper of its own is the
        sample's."""
        key = ("gaia", "dr3", "3195919254111315712")
        papers = ("teff", "logg", "mass")
        found = star_references(StarObject(8, "40 Eri B", None, key, papers=papers))
        obrien = [REFERENCES["obrien_2024"]._asdict()]
        assert found == {
            "paper_teff": obrien,
            "paper_logg": obrien,
            "paper_mass": obrien,
        }

    def test_description(self):
        assert has_description({"wikipedia": {"extract": "Sirius is…"}})
        assert not has_description({"wikipedia": {"url": "https://en…"}})
        assert not has_description({"description": "star"})
        assert not has_description(None)


class TestGalaxyEntries:
    """The entry of a galaxy of the galaxy list."""

    MILKY_WAY = StarObject(
        9, "Milky Way", "Q321", object_type="galaxy", galaxy="milky-way"
    )

    @pytest.fixture
    def entries(self, monkeypatch):
        summary = WikipediaSummary(extract="The Milky Way is…", url="https://en…")
        monkeypatch.setattr(
            stars, "load_wikipedia_summaries_for_qid", lambda qid: {"en": summary}
        )
        monkeypatch.setattr(
            stars, "collect_star_images", lambda qid: [{"file": "Milky Way.jpg"}]
        )
        labels = {"en": "Milky Way", "fr": "Voie lactée", "de": "Milchstraße"}
        entities = fake_entities({"Q321": entity(labels)}, sitelinks={"Q321": 211})
        return star_entries([self.MILKY_WAY], entities)

    def test_global(self, entries):
        entry = entries[0]["x-9"]
        assert (entry["type"], entry["name"]) == ("galaxy", "Milky Way")
        assert entry["cross_refs"] == {"wikidata_qid": "Q321"}
        assert entry["sitelinks_count"] == 211
        assert entry["images"] == [{"file": "Milky Way.jpg"}]

    def test_it_is_localized_as_a_star_is(self, entries):
        localized = entries[1]
        assert localized["fr"]["x-9"]["name"] == "Voie lactée"
        assert "name" not in localized["en"]["x-9"]
        assert has_description(localized["en"]["x-9"])

    def test_the_galaxy_of_the_sun_has_no_constellation(self, monkeypatch):
        monkeypatch.setattr(stars, "load_wikipedia_summaries_for_qid", lambda qid: {})
        monkeypatch.setattr(stars, "collect_star_images", lambda qid: None)
        # Wikidata gives the Milky Way 22 constellations.
        claims = {"P59": items("Q8679", "Q8866"), "P361": items("Q3")}
        referenced = {
            "Q8679": entity({"en": "Pisces"}),
            "Q3": entity({"en": "Local Group"}),
        }
        item = entity({"en": "Milky Way"}, claims=claims)
        other = StarObject(8, "Other", "Q5", object_type="galaxy", galaxy="other")
        entities = fake_entities({"Q321": item, "Q5": item}, referenced)
        _, localized = star_entries([self.MILKY_WAY, other], entities)
        assert localized["en"]["x-9"] == {"part_of": [{"name": "Local Group"}]}
        assert "iau_constellation" in localized["en"]["x-8"]

    def test_references_by_column_group(self, entries):
        works = galaxy_literature.REFERENCES
        references = entries[0]["x-9"]["references"]
        assert list(references) == [
            "position",
            "distance",
            "morphology",
            "stellar_mass",
            "total_mass",
            "star_formation_rate",
        ]
        assert references["position"] == [works["xu_2022"]._asdict()]
        assert [work["short"] for work in references["distance"]] == [
            "GRAVITY Collaboration 2022",
            "GRAVITY Collaboration 2021",
        ]

    def test_facts(self, entries):
        facts = entries[0]["x-9"]["facts"]
        assert set(facts) <= set(galaxy_literature.FACTS)
        works = galaxy_literature.REFERENCES
        assert facts["half_light_radius"] == {
            "value": 5750,
            "lower": 5370,
            "upper": 6130,
            "references": [works["lian_2024"]._asdict()],
        }
        # The paper gives no error.
        assert facts["age"] == {
            "value": 13.0,
            "references": [works["xiang_rix_2022"]._asdict()],
        }
        # A lower limit.
        assert facts["disc_radius"] == {
            "lower": 26000,
            "references": [works["lopez_corredoira_2018"]._asdict()],
        }

    def test_an_estimate_says_so_and_cites_its_inputs(self, entries):
        works = galaxy_literature.REFERENCES
        # A range: the inputs do not support one number.
        assert entries[0]["x-9"]["facts"]["star_count"] == {
            "lower": 1e11,
            "upper": 2e11,
            "estimate": True,
            "references": [
                works["cautun_2020"]._asdict(),
                works["chabrier_2003"]._asdict(),
            ],
        }
        planets = entries[0]["x-9"]["facts"]["planet_count"]
        assert (planets["lower"], planets["upper"]) == (8e10, 5e11)
        assert "value" not in planets
        period = entries[0]["x-9"]["facts"]["orbital_period"]
        assert (period["value"], period["estimate"]) == (212.0, True)
        assert period["references"] == [works["reid_2019"]._asdict()]
        assert "estimate" not in entries[0]["x-9"]["facts"]["planets_per_star"]

    def test_a_star_has_no_facts(self):
        assert star_facts(StarObject(7, "η Carinae", "Q1", ETA_CAR)) == {}

    def test_a_key_that_the_list_no_longer_has_cites_nothing(self):
        gone = StarObject(8, "Gone", None, object_type="galaxy", galaxy="gone")
        assert star_facts(gone) == {} and star_references(gone) == {}

    def test_a_galaxy_of_the_registry(self, tmp_path):
        built = write_registry(
            tmp_path / "reg",
            [star(10.0, 10.0)],
            galaxies=[
                galaxy(266.4, -29.0, key="milky-way", name="Milky Way", qid="Q321"),
                galaxy(10.7, 41.3, key="other", name="Other"),
            ],
        )
        found, _ = read_extrasolar_objects(built.root)
        milky_way, other = built.galaxies
        assert sorted(found, key=lambda entry: entry.name) == [
            StarObject(
                milky_way, "Milky Way", "Q321", None, "galaxy", galaxy="milky-way"
            ),
            StarObject(other, "Other", None, None, "galaxy", galaxy="other"),
        ]


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

    def test_a_star_cites_the_paper_groups_of_its_row(self, tmp_path):
        """The papers of a star with a literature key are the paper groups
        that its Point source row holds."""

        def key(rows: list[dict], at: int) -> None:
            rows[at]["cross_ids"] += [
                {
                    "catalogue": "literature",
                    "release": "star",
                    "catalogue_id": f"gaia/dr3/{at}",
                }
            ]
            rows[at]["object"] = True

        def tamper(_: list[dict], meta: list[dict]) -> None:
            key(meta, 0)
            key(meta, 1)

        white_dwarf = star(10.0, 20.0) | {
            "teff_literature": 5000.0,
            "paper_teff_source": "literature",
            "mass_literature": 0.6,
            "paper_mass_source": "literature",
        }
        rows = [white_dwarf, star(200.0, -40.0)]
        built = write_registry(tmp_path / "reg", rows, tamper=tamper)
        stars, _ = read_extrasolar_objects(built.root)
        assert {found.id: found.papers for found in stars} == {
            built.ids[0]: ("teff", "mass"),
            built.ids[1]: (),
        }


class TestStarDrawnAsAPlanet:
    """A star that a planet record also is, drawn as the planet, has no entry:
    the planet has the page."""

    def _stars(self, tmp_path, as_star: bool) -> list:
        stars = [
            star(10, 20, 50, name="Host"),
            star(10, 21, 50, name="B") | {"_qid": "Q7"},
        ]
        record = planet(0, 1) | {"_star": 1, "as_star": as_star}
        built = write_registry(tmp_path / "reg", stars, planets=[record])
        return [s.qid for s in read_extrasolar_objects(built.root)[0]]

    def test_drawn_as_the_planet(self, tmp_path):
        assert self._stars(tmp_path, False) == []

    def test_drawn_as_its_star(self, tmp_path):
        assert self._stars(tmp_path, True) == ["Q7"]


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
