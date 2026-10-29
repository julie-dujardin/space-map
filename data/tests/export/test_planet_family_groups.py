"""Tests for the planet family (``planet-``) groups."""

import gzip
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from space_map_data.constants.planets import families as planet_constants
from space_map_data.constants.planets.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PLANET_FAMILY_PAGES,
)
from space_map_data.constants.stars.families import STAR_FAMILY_PAGES
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
from space_map_data.export.notable import notable_entries
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


class TestParents:
    """The breadcrumb climbs the parent families."""

    def test_parents(self):
        assert planet_family.PAGES.parent_slugs("planet-jupiter-analogue") == [
            "planet-cold-jupiter"
        ]
        assert planet_family.PAGES.parent_slugs("planet-super-earth") == [
            "planet-classification"
        ]
        assert planet_family.PAGES.parent_slugs("planet-classification") == []


def _read_bundle(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))


def _with_qid(row: dict, qid: str) -> dict:
    item = {"catalogue": "wikidata", "release": "qid", "catalogue_id": qid}
    return row | {"cross_ids": [*row["cross_ids"], item]}


def _id(host: int, number: int) -> str:
    return f"x-{host}-b-{number}"


class TestBuild:
    """Counts and planets from the served planet files."""

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
                planet(1, 3, period=50.0),  # warm
            ],
        )
        out = tmp_path / "space-map-extrasolar"
        export_extrasolar(built.root, out, workers=1, cultures_dir=tmp_path / "none")
        return built.ids, out

    def test_counts_and_children(self, served):
        _, out = served
        groups = planet_family.build_planet_family_groups(_entities({}), out)
        assert set(groups.member_counts) == {f"planet-{f}" for f in FAMILIES}
        assert groups.member_counts["planet-gas-giant"] == 4
        assert groups.member_counts["planet-classification"] == 5
        stats = groups.extra_stats["planet-classification"]
        assert (stats.published_planet_count, stats.estimated_planet_count) == (4, 1)
        assert groups.member_counts["planet-mini-neptune"] == 1
        assert groups.children["planet-gas-giant"] == [
            "planet-hot-jupiter",
            "planet-warm-jupiter",
        ]
        assert groups.children["planet-classification"] == [
            "planet-giant-planet",
            "planet-mini-neptune",
        ]
        assert "planet-cold-jupiter" not in groups.children["planet-gas-giant"]

    def test_planets_with_an_article_then_the_nearest(self, served):
        ids, out = served
        entities = _entities({"Q1": (5, ["de"]), "Q2": (90, []), "Q3": (40, ["en"])})
        groups = planet_family.build_planet_family_groups(entities, out)
        gas = groups.notable_members["planet-gas-giant"]
        assert [m.object_id for m in gas] == [
            _id(ids[1], 1),
            _id(ids[0], 1),
            _id(ids[0], 2),
            _id(ids[1], 3),
        ]
        assert [m.sitelinks_count for m in gas] == [40, 5, None, None]
        assert [m.wikidata_qid for m in gas] == ["Q3", "Q1", "Q2", None]
        assert all(m.extrasolar for m in gas)
        hot = groups.notable_members["planet-hot-jupiter"]
        assert [m.object_id for m in hot] == [_id(ids[1], 1), _id(ids[0], 2)]
        assert "planet-classification" not in groups.notable_members
        assert "planet-mini-neptune" not in groups.notable_members

        entries = notable_entries(gas, entities)
        assert [e["name"] for e in entries] == [
            "Label Q3",
            "Label Q1",
            "Label Q2",
            "Planet 1 3",
        ]

    def test_the_list_stops_at_its_size(self, served, monkeypatch):
        ids, out = served
        monkeypatch.setattr(planet_family, "NOTABLE_PLANETS", 2)
        groups = planet_family.build_planet_family_groups(_entities({}), out)
        gas = groups.notable_members["planet-gas-giant"]
        assert [m.object_id for m in gas] == [_id(ids[0], 1), _id(ids[0], 2)]

    def test_no_served_export(self, tmp_path):
        groups = planet_family.build_planet_family_groups(
            _entities({}), tmp_path / "none"
        )
        assert groups.member_counts == {}
        assert groups.notable_members == {}
        assert groups.children == {}
        assert planet_family.served_planet_families_stamp(tmp_path / "none") is None

    def test_an_export_without_planet_families_is_refused(self, tmp_path):
        root = tmp_path / "old" / "v1" / "x"
        root.mkdir(parents=True)
        (root / "metadata.json").write_text(json.dumps({"planets": {"token": "0"}}))
        with pytest.raises(KeyError):
            planet_family.build_planet_family_groups(_entities({}), tmp_path / "old")
        with pytest.raises(KeyError):
            planet_family.served_planet_families_stamp(tmp_path / "old")

    def test_stamp_is_the_served_counts_and_planets_token(self, served):
        _, out = served
        stamp = planet_family.served_planet_families_stamp(out)
        assert stamp is not None
        assert [entry["slug"] for entry in stamp["families"]] == list(FAMILIES)
        reader = ExportReader(out / "v1" / "x")
        assert stamp["planets"] == reader.metadata["planets"]["token"]


class TestBundles:
    """The export writes no planet family page yet."""

    def test_no_bundle(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        group = GROUP_BY_SLUG[f"{FAMILY_SLUG_PREFIX}hot-jupiter"]
        root = GROUP_BY_SLUG[f"{FAMILY_SLUG_PREFIX}{planet_constants.ROOT_FAMILY}"]
        monkeypatch.setattr(bundles, "GROUPS", (root, group))
        monkeypatch.setattr(bundles, "collect_group_images", lambda slug: None)
        monkeypatch.setattr(bundles, "load_wikipedia_summaries_for_qid", lambda qid: {})
        monkeypatch.setattr(bundles, "load_wikipedia_sections_for_qid", lambda qid: {})
        (tmp_path / "groups").mkdir()
        entities = MagicMock()
        entities.get_referenced.return_value = None

        bundles.write_group_bundles(
            tmp_path,
            entities,
            {},
            {},
            extra_member_counts={root.slug: 7, group.slug: 3},
            extra_stats={
                group.slug: GroupExtraStats(
                    published_planet_count=2, estimated_planet_count=1
                )
            },
        )

        index = json.loads((tmp_path / "groups" / "__index__.json").read_bytes())
        assert index == {}
        found = {}
        for path in (tmp_path / "groups").glob("*/*.json.gz"):
            found.update(_read_bundle(path))
        assert found == {}
