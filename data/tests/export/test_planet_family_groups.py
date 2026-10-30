"""Tests for the planet family (``planet-``) groups."""

import gzip
import json
from pathlib import Path

import pytest

from space_map_data.constants.planets.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PLANET_FAMILY_PAGES,
)
from space_map_data.constants.stars.families import STAR_FAMILY_PAGES
from space_map_data.constants.wikidata_topics import topic_page_qids
from space_map_data.download.providers.wikidata.downloader import family_page_qids
from space_map_data.export.extrasolar.build import export_extrasolar
from space_map_data.export.extrasolar.reader import ExportReader
from space_map_data.export.groups import bundles, planet_family
from space_map_data.export.groups.registry import (
    GROUP_BY_SLUG,
    GROUPS,
    GroupCategory,
    GroupType,
)
from space_map_data.export.groups.stats import GroupExtraStats
from space_map_data.export.notable import (
    NotableObject,
    notable_entries,
    notable_names,
)
from space_map_data.export.objects.wikipedia import WikipediaSummary
from space_map_data.export.solar_planets import solar_planet_records
from tests.export.test_solar_planets import ELEMENTS, GMS, RADII
from tests.export.test_star_family_groups import _entities
from tests.extrasolar.export_registry import planet, star, write_registry


class TestRegistry:
    """One group per family."""

    def test_every_family_has_a_group(self):
        for family, qids in PLANET_FAMILY_PAGES.items():
            group = GROUP_BY_SLUG[f"{FAMILY_SLUG_PREFIX}{family}"]
            assert group.type is GroupType.PLANET_FAMILY
            assert group.applies_to is GroupCategory.PLANET
            assert group.wikidata_qid == qids[0]

    def test_the_prefix_is_only_the_families(self):
        slugs = [g.slug for g in GROUPS if g.slug.startswith(FAMILY_SLUG_PREFIX)]
        assert len(slugs) == len(FAMILIES)
        assert all(
            GROUP_BY_SLUG[slug].type is GroupType.PLANET_FAMILY for slug in slugs
        )


class TestDownloader:
    """The Wikidata downloader seeds the family items."""

    def test_seeds_every_family_qid(self):
        seeded = family_page_qids()
        for pages in (PLANET_FAMILY_PAGES, STAR_FAMILY_PAGES):
            for qids in pages.values():
                assert set(qids) <= seeded

    def test_the_exoplanets_tab_is_a_topic_page(self):
        assert "Q44559" in topic_page_qids()


class TestParents:
    """The breadcrumb climbs the parent families, then the Planets page."""

    def test_parents(self):
        assert planet_family.PAGES.parent_slugs("planet-jupiter-analogue") == [
            "planet-cold-jupiter"
        ]
        assert planet_family.PAGES.parent_slugs("planet-ice-giant") == [
            "planet-giant-planet"
        ]
        assert planet_family.PAGES.parent_slugs("planet-super-earth") == ["cat-planets"]


def _read_bundle(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))


def _read_all(root: Path) -> dict:
    found = {}
    for path in root.glob("*.json.gz"):
        found.update(_read_bundle(path))
    return found


def _with_qid(row: dict, qid: str) -> dict:
    item = {"catalogue": "wikidata", "release": "qid", "catalogue_id": qid}
    return row | {"cross_ids": [*row["cross_ids"], item]}


def _id(host: int, number: int) -> str:
    return f"x-{host}-b-{number}"


def _body(object_id: str, qid: str, name: str) -> NotableObject:
    return NotableObject(object_id, qid, name, None, None, mass_kg=1.0)


# Earth and Jupiter, with test QIDs.
SOLAR = planet_family.SolarPlanets(
    [_body("naif-399", "Q399", "Earth"), _body("naif-599", "Q599", "Jupiter")],
    solar_planet_records(RADII, GMS, ELEMENTS),
)
# Sitelinks of the test items: the Solar System planets have the most.
SITELINKS = {
    "Q1": (5, ["de"]),
    "Q2": (90, []),
    "Q3": (40, ["en"]),
    "Q399": (0, ["en", *(f"x{n}" for n in range(300))]),
    "Q599": (0, ["en", *(f"x{n}" for n in range(250))]),
}


class TestBuild:
    """Counts and planets from the served planet files and the Solar System."""

    @pytest.fixture
    def served(self, tmp_path):
        built = write_registry(
            tmp_path / "reg",
            [star(10.0, 5.0, 50.0, name="Near"), star(11.0, 5.0, 5.0, name="Far")],
            planets=[
                _with_qid(planet(0, 1), "Q1"),  # warm
                _with_qid(planet(0, 2, period=3.0), "Q2"),  # hot
                _with_qid(planet(1, 1, period=3.0), "Q3"),  # hot
                planet(1, 2, mass=None, radius=0.25, estimated=["radius"]),
                # warm, and a super-Jupiter by its minimum mass
                planet(1, 3, period=50.0, mass=3.0, mass_kind="minimum"),
                planet(1, 4, mass=30.0, **{"class": "brown dwarf"}),
            ],
        )
        out = tmp_path / "space-map-extrasolar"
        export_extrasolar(built.root, out, workers=1, cultures_dir=tmp_path / "none")
        return built.ids, out

    def test_counts_and_children(self, served):
        _, out = served
        groups = planet_family.build_planet_family_groups(_entities({}), SOLAR, out)
        assert set(groups.member_counts) == {f"planet-{f}" for f in FAMILIES}
        assert groups.member_counts["planet-gas-giant"] == 5
        stats = groups.extra_stats["planet-gas-giant"]
        assert (stats.published_planet_count, stats.estimated_planet_count) == (5, 0)
        assert groups.member_counts["planet-mini-neptune"] == 1
        assert groups.member_counts["planet-terrestrial-planet"] == 1
        assert groups.member_counts["planet-ice-giant"] == 0
        assert groups.children["planet-gas-giant"] == [
            "planet-hot-jupiter",
            "planet-warm-jupiter",
            "planet-cold-jupiter",
            "planet-super-jupiter",
        ]
        assert groups.children["cat-planets"] == [
            "planet-giant-planet",
            "planet-goldilocks-planet",
            "planet-mini-neptune",
            "planet-terrestrial-planet",
        ]

    def test_planets_with_an_article_then_the_nearest(self, served):
        ids, out = served
        entities = _entities(SITELINKS)
        groups = planet_family.build_planet_family_groups(entities, SOLAR, out)
        gas = groups.notable_members["planet-gas-giant"]
        assert [m.object_id for m in gas] == [
            "naif-599",
            _id(ids[1], 1),
            _id(ids[0], 1),
            _id(ids[0], 2),
            _id(ids[1], 3),
        ]
        assert [m.sitelinks_count for m in gas] == [251, 40, 5, None, None]
        assert [m.wikidata_qid for m in gas] == ["Q599", "Q3", "Q1", "Q2", None]
        assert [m.extrasolar for m in gas] == [False, True, True, True, True]
        assert gas[0].mass_kg == 1.0
        hot = groups.notable_members["planet-hot-jupiter"]
        assert [m.object_id for m in hot] == [_id(ids[1], 1), _id(ids[0], 2)]
        earth = groups.notable_members["planet-goldilocks-planet"]
        assert [m.object_id for m in earth] == ["naif-399"]
        assert "planet-mini-neptune" not in groups.notable_members

        entries = notable_entries(gas, entities)
        assert [e["name"] for e in entries] == [
            "Label Q599",
            "Planet 1 1",
            "Planet 0 1",
            "Planet 0 2",
            "Planet 1 3",
        ]

    def test_a_planet_is_listed_by_its_page_names(self, served):
        ids, out = served
        entities = _entities({"Q2": (90, []), "Q3": (40, ["en"])})
        labels = {"en": "Label Q3", "de": "Zeta b", "fr": "Osiris"}
        listed = entities.get_listed_star.side_effect
        entities.get_listed_star.side_effect = lambda qid: (
            listed(qid) | {"labels": labels} if qid == "Q3" else listed(qid)
        )
        groups = planet_family.build_planet_family_groups(entities, SOLAR, out)
        hot = groups.notable_members["planet-hot-jupiter"]
        entries = notable_entries(hot, entities)
        assert [e["name"] for e in entries] == ["Planet 1 1", "Planet 0 2"]
        # A nickname is an alias of the page, not its name.
        key = _id(ids[1], 1)
        assert notable_names(hot, entries, "de", entities) == {key: "Zeta b"}
        assert notable_names(hot, entries, "fr", entities) == {}

    def test_the_list_stops_at_its_size(self, served, monkeypatch):
        ids, out = served
        monkeypatch.setattr(planet_family, "NOTABLE_PLANETS", 2)
        groups = planet_family.build_planet_family_groups(_entities({}), SOLAR, out)
        gas = groups.notable_members["planet-gas-giant"]
        assert [m.object_id for m in gas] == ["naif-599", _id(ids[0], 1)]

    def test_no_served_export(self, tmp_path):
        """The Solar System planets still count and list."""
        groups = planet_family.build_planet_family_groups(
            _entities({}), SOLAR, tmp_path / "none"
        )
        assert groups.member_counts["planet-gas-giant"] == 1
        assert groups.member_counts["planet-hot-jupiter"] == 0
        assert [m.object_id for m in groups.notable_members["planet-gas-giant"]] == [
            "naif-599"
        ]
        assert groups.children["cat-planets"] == [
            "planet-giant-planet",
            "planet-goldilocks-planet",
            "planet-terrestrial-planet",
        ]
        assert groups.planets is not None
        assert groups.planets.member_count == 2
        assert groups.planets.stats.exoplanet_count == 0
        assert planet_family.served_planet_families_stamp(tmp_path / "none") is None

    def test_an_export_without_planet_families_is_refused(self, tmp_path):
        root = tmp_path / "old" / "v1" / "x"
        root.mkdir(parents=True)
        (root / "metadata.json").write_text(json.dumps({"planets": {"token": "0"}}))
        with pytest.raises(KeyError):
            planet_family.build_planet_family_groups(
                _entities({}), SOLAR, tmp_path / "old"
            )
        with pytest.raises(KeyError):
            planet_family.served_planet_families_stamp(tmp_path / "old")

    def test_stamp_is_the_served_counts_and_planets_token(self, served):
        _, out = served
        stamp = planet_family.served_planet_families_stamp(out)
        assert stamp is not None
        assert [entry["slug"] for entry in stamp["families"]] == list(FAMILIES)
        reader = ExportReader(out / "v1" / "x")
        assert stamp["planets"] == reader.metadata["planets"]["token"]


class TestPlanetsPage:
    """The Planets page counts, lists, ranks and plots every planet."""

    @pytest.fixture
    def page(self, tmp_path):
        built = write_registry(
            tmp_path / "reg",
            [star(10.0, 5.0, 50.0, name="Near")],
            planets=[
                _with_qid(planet(0, 1, radius=1.5), "Q1"),
                planet(0, 2, mass=3.0, mass_kind="minimum", radius=2.0),
                planet(0, 3, mass=12.0, radius=2.5, estimated=["radius"]),
                planet(0, 4, mass=0.01, limits=["mass<"], semi_major_axis=None),
                planet(0, 5, mass=30.0, **{"class": "brown dwarf"}),
            ],
        )
        out = tmp_path / "space-map-extrasolar"
        export_extrasolar(built.root, out, workers=1, cultures_dir=tmp_path / "none")
        groups = planet_family.build_planet_family_groups(
            _entities(SITELINKS), SOLAR, out
        )
        assert groups.planets is not None
        return built.ids, groups

    def test_counts(self, page):
        _, groups = page
        planets = groups.planets
        assert planets.member_count == 6
        stats = planets.stats
        assert (stats.solar_member_count, stats.exoplanet_count) == (2, 4)
        assert (stats.published_planet_count, stats.estimated_planet_count) == (5, 0)
        assert stats.planet_family_count == sum(
            1 for n in groups.member_counts.values() if n
        )

    def test_the_solar_system_leads_the_list(self, page):
        ids, groups = page
        assert [m.object_id for m in groups.planets.notable_members] == [
            "naif-399",
            "naif-599",
            _id(ids[0], 1),
            _id(ids[0], 2),
            _id(ids[0], 3),
            _id(ids[0], 4),
        ]
        assert [m.object_id for m in groups.planets.solar_members] == [
            "naif-399",
            "naif-599",
        ]

    def test_an_exoplanet_entry_has_its_diameter_and_year(self, page):
        """The diameter of a measured radius and the discovery year. A Solar
        System planet keeps its lineup entry."""
        ids, groups = page
        members = groups.planets.notable_members
        assert {m.object_id: (m.diameter_km, m.first_obs) for m in members} == {
            "naif-399": (None, None),
            "naif-599": (None, None),
            _id(ids[0], 1): (214500.0, "2000"),
            _id(ids[0], 2): (286000.0, "2000"),
            _id(ids[0], 3): (None, "2000"),
            _id(ids[0], 4): (None, "2000"),
        }
        entries = notable_entries(members, _entities(SITELINKS))
        assert (entries[2]["diameter_km"], entries[2]["first_obs"]) == (
            214500.0,
            "2000",
        )
        assert "diameter_km" not in entries[4]

    def test_largest_and_most_massive(self, page):
        """The largest measured radius of a planet with a measured true mass;
        a minimum mass counts for the most massive and says so."""
        ids, groups = page
        assert groups.planets.stats.largest_planet == {
            "primary_type": "object",
            "primary_id": _id(ids[0], 1),
            "name": "Planet 0 1",
            "radius_earth": 16.81,
        }
        assert groups.planets.stats.most_massive_planet == {
            "primary_type": "object",
            "primary_id": _id(ids[0], 3),
            "name": "Planet 0 3",
            "mass_earth": 3814.0,
            "mass_kind": "true",
        }

    def test_plot(self, page):
        _, groups = page
        plot = groups.planets.plot
        assert plot["solar"] == ["naif-399", "naif-599"]
        assert plot["mass"] == [1.0, 317.8, 317.8, 953.5, 3814.0, None]
        assert plot["mass_flag"] == [0, 0, 0, 1, 0, None]
        assert plot["radius"] == [1.0, 11.21, 16.81, 22.42, 28.02, None]
        assert plot["radius_flag"] == [0, 0, 0, 0, 2, None]
        assert plot["semi_major_axis"] == [1.0, 5.203, 0.09, 0.09, 0.09, None]
        assert plot["semi_major_axis_flag"] == [0, 0, 0, 0, 0, None]

    def test_the_plot_file(self, page, tmp_path):
        _, groups = page
        planet_family.write_planet_plot(tmp_path, groups.planets.plot)
        found = _read_bundle(tmp_path / "groups" / "__planet_plot__.json.gz")
        assert found == groups.planets.plot


class TestListEntry:
    """An exoplanet entry takes a measured radius only."""

    @staticmethod
    def _record(**values) -> dict:
        return {
            "families": [],
            "families_estimated": [],
            "values": {"radius": 1.5, "discovery_year": 1995} | values,
            "assumed": [],
            "estimated": [],
            "limits": [],
        }

    @pytest.mark.parametrize(
        ("flags", "diameter"),
        [
            ({}, 214500.0),
            ({"estimated": ["radius"]}, None),
            ({"limits": ["radius<"]}, None),
            ({"assumed": ["radius"]}, None),
        ],
    )
    def test_diameter(self, flags, diameter):
        found = planet_family._planet(self._record() | flags, "x-1-b-1", "b", 1.0)
        assert (found.diameter_km, found.first_obs) == (diameter, "1995")

    def test_no_discovery_year(self):
        record = self._record(discovery_year=None)
        assert planet_family._planet(record, "x-1-b-1", "b", 1.0).first_obs is None


class TestBundles:
    """A family page climbs to its parent family or to the Planets page, and
    the Planets page carries its Solar System planets and its tab text."""

    def test_bundle(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        slugs = (
            "cat-solar-system",
            "cat-planets",
            "planet-super-earth",
            "planet-hot-jupiter",
        )
        monkeypatch.setattr(bundles, "GROUPS", tuple(GROUP_BY_SLUG[s] for s in slugs))
        monkeypatch.setattr(bundles, "collect_group_images", lambda slug: None)
        monkeypatch.setattr(
            bundles,
            "load_wikipedia_summaries_for_qid",
            lambda qid: (
                {"en": WikipediaSummary("Exoplanets are…", url="https://x")}
                if qid == "Q44559"
                else {}
            ),
        )
        monkeypatch.setattr(bundles, "load_wikipedia_sections_for_qid", lambda qid: {})
        (tmp_path / "groups").mkdir()
        exoplanet = {
            "labels": {"en": "exoplanet", "de": "Exoplanet"},
            "descriptions": {"en": "planet outside the Solar System"},
            "aliases": {},
            "claims": {},
            "sitelinks": {},
        }
        entities = _entities({"Q399": (0, ["en"])})
        entities.get_referenced.side_effect = lambda qid: (
            exoplanet if qid == "Q44559" else None
        )
        earth = _body("naif-399", "Q399", "Earth")

        bundles.write_group_bundles(
            tmp_path,
            entities,
            {},
            {},
            extra_member_counts={"cat-planets": 7, "planet-hot-jupiter": 3},
            extra_notable_members={"cat-planets": [earth]},
            extra_member_lists={"cat-planets": {"solar_members": [earth]}},
            extra_stats={
                "cat-planets": GroupExtraStats(
                    moon_total=3, solar_member_count=1, exoplanet_count=6
                ),
                "planet-hot-jupiter": GroupExtraStats(
                    published_planet_count=2, estimated_planet_count=1
                ),
            },
            child_slugs_by_group={
                "cat-solar-system": ["cat-planets"],
                "cat-planets": ["planet-hot-jupiter"],
            },
            child_counts_by_group={"cat-solar-system": {"cat-planets": 1}},
        )

        index = json.loads((tmp_path / "groups" / "__index__.json").read_bytes())
        assert index["planet-hot-jupiter"] == {
            "type": "planet_family",
            "applies_to": "planet",
            "n": 3,
        }
        assert index["cat-planets"]["n"] == 7
        found = _read_all(tmp_path / "groups" / "__global__")
        page = found["planet-hot-jupiter"]
        assert page["parent_families"] == ["planet-gas-giant"]
        counts = page["published_planet_count"], page["estimated_planet_count"]
        assert counts == (2, 1)
        assert found["planet-super-earth"]["parent_families"] == ["cat-planets"]
        planets = found["cat-planets"]
        assert [m["id"] for m in planets["solar_members"]] == ["naif-399"]
        assert planets["solar_members"][0]["mass_kg"] == 1.0
        assert planets["exoplanets_qid"] == "Q44559"
        assert (planets["solar_member_count"], planets["exoplanet_count"]) == (1, 6)
        assert planets["moon_total"] == 3
        assert "parent_families" not in planets

        en = _read_all(tmp_path / "groups" / "en")
        assert en["cat-planets"]["exoplanets"] == {
            "name": "exoplanet",
            "description": "planet outside the Solar System",
            "wikipedia": {"extract": "Exoplanets are…", "url": "https://x"},
        }
        tile = en["cat-solar-system"]["child_groups"]
        assert [(c["primary_id"], c["n"]) for c in tile] == [("cat-planets", 1)]
        de = _read_all(tmp_path / "groups" / "de")
        assert de["cat-planets"]["exoplanets"] == {"name": "Exoplanet"}
