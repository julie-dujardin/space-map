"""Tests for the objects search-index field builders."""

import gzip
import json

from space_map_data.search.indices import objects
from space_map_data.search.indices.base import object_pk
from space_map_data.search.indices.objects import (
    _class_pages,
    _date_to_int,
    _inception,
    _load_earth_membership,
    _load_system_moons,
    _radii_diameter_km,
    _search_type,
    _small_body_groups,
    _spacecraft_category,
)


class TestDateToInt:
    """`_date_to_int` parses assorted date strings into sortable YYYYMMDD ints."""

    def test_full_iso(self):
        assert _date_to_int("1957-10-04") == 19571004

    def test_year_only_defaults_to_jan_1(self):
        assert _date_to_int("1801") == 18010101

    def test_wikidata_signed_time(self):
        assert _date_to_int("+1957-10-04T00:00:00Z") == 19571004

    def test_zero_month_and_day_default_to_one(self):
        assert _date_to_int("2018-00-00") == 20180101

    def test_unparseable_returns_none(self):
        assert _date_to_int("not a date") is None


class TestInception:
    """`_inception` picks one sortable date by source precedence."""

    def test_prefers_sbdb_first_obs(self):
        g = {
            "sbdb": {"first_obs": "1801-01-01"},
            "celestrak": {"launch_date": "2020-05-30"},
        }
        assert _inception(g) == 18010101

    def test_falls_back_to_launch_date(self):
        assert _inception({"celestrak": {"launch_date": "2020-05-30"}}) == 20200530

    def test_wikidata_inception_last_resort(self):
        assert (
            _inception({"wikidata": {"inception": "+1999-12-31T00:00:00Z"}}) == 19991231
        )

    def test_discovery_date_list(self):
        assert _inception({"wikidata": {"discovery_date": ["1846-09-23"]}}) == 18460923

    def test_none_when_absent(self):
        assert _inception({"type": "moon"}) is None


class TestSmallBodyGroups:
    """`_small_body_groups` mirrors the export/groups/registry.py slug scheme."""

    def test_class_and_flags(self):
        assert _small_body_groups({"class": "MBA", "neo": True, "pha": True}) == [
            "class-MBA",
            "flag-neo",
            "flag-pha",
        ]

    def test_empty_when_no_signal(self):
        assert _small_body_groups({}) == []


class TestSpacecraftCategory:
    """`_spacecraft_category` splits tracked craft into satellites, debris and
    probes."""

    def test_celestrak_spacecraft_is_satellite(self):
        assert _spacecraft_category(
            {"celestrak": {"ops_status": "+"}}, "spacecraft"
        ) == ("cat-satellites")

    def test_spacecraft_without_celestrak_is_probe(self):
        assert _spacecraft_category({}, "spacecraft") == "cat-probes"

    def test_celestrak_debris_is_debris(self):
        assert (
            _spacecraft_category({"celestrak": {"ops_status": "?"}}, "debris")
            == "cat-debris"
        )

    def test_debris_without_celestrak_is_none(self):
        assert _spacecraft_category({}, "debris") is None

    def test_non_spacecraft_is_none(self):
        assert _spacecraft_category({"celestrak": {"ops_status": "+"}}, "moon") is None


class TestClassGroups:
    """The bodies of the Solar System that no catalogue tags with a family."""

    def test_a_planet_is_on_the_pages_above_its_families(self):
        groups = _class_pages(
            "naif-599", {"type": "planet", "planet_families": ["jupiter-analogue"]}
        )
        assert set(groups) == {
            "cat-planets",
            "planet-jupiter-analogue",
            "planet-cold-jupiter",
            "planet-gas-giant",
            "planet-giant-planet",
        }

    def test_the_sun_has_the_families_of_its_spectral_type(self):
        groups = _class_pages("naif-10", {"type": "star"})
        assert {"cat-stars", "star-g-type-main-sequence", "star-dwarf"} <= set(groups)
        assert "star-classification" not in groups

    def test_another_body_has_none(self):
        assert _class_pages("naif-301", {"type": "moon"}) == []


class TestRadiiDiameterKm:
    """`_radii_diameter_km` gives moons/planets a diameter sort key from PCK radii."""

    def test_mean_triaxial(self):
        assert _radii_diameter_km({"a": 1820.0, "b": 1815.0, "c": 1810.0}) == 3630.0

    def test_partial_radii(self):
        assert _radii_diameter_km({"a": 100.0, "c": 200.0}) == 300.0

    def test_none_when_empty(self):
        assert _radii_diameter_km({}) is None


class TestLoadEarthMembership:
    """`_load_earth_membership` inverts the {slug: [ids]} index to {id: [slugs]}."""

    def test_inverts(self, tmp_path):
        membership_dir = tmp_path / "v1" / "membership"
        membership_dir.mkdir(parents=True)
        (membership_dir / "earth.json.gz").write_bytes(
            gzip.compress(
                json.dumps({"starlink": ["a", "b"], "op-spacex": ["a"]}).encode()
            )
        )
        assert _load_earth_membership(tmp_path) == {
            "a": ["starlink", "op-spacex"],
            "b": ["starlink"],
        }

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_earth_membership(tmp_path) == {}


class TestSystemMoons:
    """`_load_system_moons` joins the Satellite Systems and Moons pages."""

    def test_a_system_has_the_moons_of_its_planet(self, tmp_path):
        directory = tmp_path / "v1" / "groups" / "__global__"
        directory.mkdir(parents=True)
        for number, groups in enumerate(
            (
                {"cat-satellite-systems": {"notable_members": [{"id": "naif-5"}]}},
                {
                    "cat-moons": {
                        "moon_counts": [
                            {"primary_id": "naif-599", "n": 116},
                            {"primary_id": "naif-999", "n": 5},
                        ]
                    }
                },
            )
        ):
            (directory / f"{number}.json.gz").write_bytes(
                gzip.compress(json.dumps(groups).encode())
            )
        assert _load_system_moons(tmp_path) == {"naif-5": 116}

    def test_no_export(self, tmp_path):
        assert _load_system_moons(tmp_path) == {}


class TestSearchType:
    def test_one_class_of_asteroid(self):
        assert _search_type("asteroid_main_belt") == "asteroid"
        assert _search_type("asteroid") == "asteroid"

    def test_another_type_stays(self):
        assert _search_type("moon") == "moon"


class TestMoons:
    """A moon's IAU flag is the DB's status in its bundle, not a rule on its
    page name."""

    def test_the_flag_comes_from_the_bundle(self, tmp_path, monkeypatch):
        monkeypatch.setattr(objects, "LANGUAGES", ("en",))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        moon = {"type": "moon", "orbit": {"parent_id": "naif-6"}}
        entries = {
            "naif-635": moon | {"id": "naif-635", "name": "Daphnis", "iau_named": True},
            # A Wikidata label with no year in it, on a moon with no name.
            "naif-65067": moon
            | {"id": "naif-65067", "name": "Moon of Saturn", "iau_named": False},
        }
        directory = tmp_path / "v1" / "objects" / "__global__"
        directory.mkdir(parents=True)
        (directory / "0.json.gz").write_bytes(
            gzip.compress(json.dumps(entries).encode())
        )
        built = list(objects.build_object_documents(tmp_path))
        docs = {doc["object"]["id"]: doc["object"] for doc in built}
        assert docs["naif-635"]["iau_named"] is True
        assert docs["naif-65067"]["iau_named"] is False
        assert all(doc["classes"] == ["moon"] for doc in built)


class TestDrawable:
    """`drawable` marks what the comparison row can size."""

    def documents(self, tmp_path, monkeypatch, entries, bundles, keep=frozenset()):
        monkeypatch.setattr(objects, "LANGUAGES", ("en",))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        directory = tmp_path / "v1" / "objects" / "__global__"
        directory.mkdir(parents=True)
        (directory / "0.json.gz").write_bytes(
            gzip.compress(json.dumps(entries).encode())
        )
        models = tmp_path / "v1" / "models"
        models.mkdir()
        (models / "index.json").write_text(json.dumps({"bundles": bundles}))
        return {
            doc["object"]["id"]: doc["object"]
            for doc in objects.build_object_documents(tmp_path, keep)
        }

    def test_a_size_or_a_sized_craft(self, tmp_path, monkeypatch):
        craft = {"type": "spacecraft", "name": "Craft"}
        docs = self.documents(
            tmp_path,
            monkeypatch,
            {
                "naif-599": {"type": "planet", "name": "J", "radii": {"a": 71492}},
                "spkid-1": {"type": "comet", "name": "C", "sbdb": {"diameter": 3.0}},
                "norad_satcat-1": craft,
                "norad_satcat-2": craft,
                "norad_satcat-3": craft,
            },
            {
                "sized": {"scale_meters": 2.0, "objects": [{"id": "norad_satcat-1"}]},
                "unsized": {"objects": [{"id": "norad_satcat-2"}]},
            },
        )
        drawable = {id_ for id_, obj in docs.items() if obj.get("drawable")}
        assert drawable == {"naif-599", "spkid-1", "norad_satcat-1"}

    def test_a_shape_model_is_no_craft(self, tmp_path, monkeypatch):
        docs = self.documents(
            tmp_path,
            monkeypatch,
            {"norad_satcat-1": {"type": "spacecraft", "name": "Craft"}},
            {
                "shape": {
                    "kind": "shape_model",
                    "scale_meters": 2.0,
                    "objects": [{"id": "norad_satcat-1"}],
                }
            },
        )
        assert "drawable" not in docs["norad_satcat-1"]

    def test_a_star_does_not_go_by_its_entry(self, tmp_path, monkeypatch):
        star = {"type": "star", "name": "S", "radii": {"a": 700000}}
        docs = self.documents(tmp_path, monkeypatch, {"x-1": star}, {}, {"x-1"})
        assert "drawable" not in docs["x-1"]


class TestExtrasolarStars:
    """A star of the extrasolar catalogue is a document when its entry in the
    base locale has a Wikipedia extract, or when it hosts planets."""

    def test_document(self, tmp_path, monkeypatch):
        monkeypatch.setattr(objects, "LANGUAGES", ("en", "ru"))
        monkeypatch.setattr(objects, "read_manual_aliases", dict)
        bundles = {
            "__global__": {
                "x-7": {
                    "id": "x-7",
                    "type": "star",
                    "name": "Vega",
                    "sitelinks_count": 120,
                },
                "x-8": {"id": "x-8", "type": "star", "name": "HD 8"},
                "x-9": {"id": "x-9", "type": "star", "name": "HD 9"},
                "naif-10": {"id": "naif-10", "type": "star", "name": "Sun"},
                # Star systems, which take the type of their class.
                "x-11": {"id": "x-11", "type": "multiple_star", "name": "α Cen"},
                "x-12": {"id": "x-12", "type": "binary_star", "name": "Kepler-16"},
            },
            "en": {
                "x-11": {"wikipedia": {"extract": "Alpha Centauri is…"}},
                "x-7": {
                    "aliases": ["Alpha Lyrae"],
                    "wikipedia": {"extract": "Vega is…"},
                },
                "x-8": {"description": "star in the constellation Lyra"},
            },
            "ru": {"x-7": {"name": "Вега"}, "x-8": {"wikipedia": {"extract": "…"}}},
        }
        for tier, entries in bundles.items():
            directory = tmp_path / "v1" / "objects" / tier
            directory.mkdir(parents=True)
            (directory / "0.json.gz").write_bytes(
                gzip.compress(json.dumps(entries).encode())
            )
        docs = {doc["id"]: doc for doc in objects.build_object_documents(tmp_path)}
        assert set(docs) == {"x-7", "x-11", "b-10"}
        assert docs["x-11"]["object"]["type"] == "multiple_star"
        hosted = objects.build_object_documents(tmp_path, {"x-8", "x-12"})
        assert {doc["id"] for doc in hosted} == {"x-7", "x-8", "x-11", "x-12", "b-10"}
        vega = docs["x-7"]
        assert vega["name"] == "Vega"
        assert vega["name_ru"] == "Вега"
        assert vega["sitelinks_count"] == 120
        assert vega["object"] == {
            "id": "x-7",
            "type": "star",
            "aliases_en": ["Alpha Lyrae"],
        }

    def test_primary_key_mirrors_the_url(self):
        assert object_pk("x-22137869") == "x-22137869"
