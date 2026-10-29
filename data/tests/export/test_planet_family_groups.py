"""Tests for the planet family (``planet-``) groups."""

import json
from unittest.mock import MagicMock

import pytest

from space_map_data.constants.planets.families import (
    FAMILIES,
    FAMILY_SLUG_PREFIX,
    PLANET_FAMILY_PAGES,
)
from space_map_data.constants.stars.families import STAR_FAMILY_PAGES
from space_map_data.download.providers.wikidata.downloader import family_page_qids
from space_map_data.export.groups import bundles
from space_map_data.export.groups.registry import (
    GROUP_BY_SLUG,
    GROUPS,
    Group,
    GroupCategory,
    GroupType,
)


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


class TestBundles:
    """The export writes no planet family page."""

    def test_no_bundle(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        star = Group(
            slug="star-classification",
            type=GroupType.STAR_FAMILY,
            applies_to=GroupCategory.STAR,
        )
        planet = GROUP_BY_SLUG[f"{FAMILY_SLUG_PREFIX}hot-jupiter"]
        monkeypatch.setattr(bundles, "GROUPS", (star, planet))
        monkeypatch.setattr(bundles, "collect_group_images", lambda slug: None)
        monkeypatch.setattr(bundles, "load_wikipedia_summaries_for_qid", lambda qid: {})
        monkeypatch.setattr(bundles, "load_wikipedia_sections_for_qid", lambda qid: {})
        (tmp_path / "groups").mkdir()

        bundles.write_group_bundles(tmp_path, MagicMock(), {}, {})

        index = json.loads((tmp_path / "groups" / "__index__.json").read_bytes())
        assert list(index) == [star.slug]
