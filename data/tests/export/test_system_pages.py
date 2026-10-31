"""The Star Systems and Planetary Systems category pages."""

from collections import Counter
from unittest.mock import MagicMock

import numpy as np

from space_map_data.constants.categories import (
    PLANETARY_SYSTEMS_SLUG,
    SOLAR_SYSTEM_SLUG,
    STAR_SYSTEMS_SLUG,
)
from space_map_data.export.groups.system_pages import (
    _root_counts,
    build_system_pages,
)
from space_map_data.export.names import ObjectNames
from tests.export.test_star_family_groups import _entities


class TestNoExport:
    """With no export served, the Solar System is the one planetary system."""

    def test_counts(self, tmp_path, session):
        pages = build_system_pages(
            [], Counter(), ObjectNames(_entities({}), session), tmp_path / "none"
        )
        assert pages.member_counts == {PLANETARY_SYSTEMS_SLUG: 1}
        stats = pages.extra_stats[PLANETARY_SYSTEMS_SLUG]
        assert stats.multi_planet_system_count == 1
        assert STAR_SYSTEMS_SLUG not in pages.member_counts

    def test_the_solar_system_is_a_member(self, tmp_path, session):
        pages = build_system_pages(
            [], Counter(), ObjectNames(_entities({}), session), tmp_path / "none"
        )
        member = pages.notable_members[PLANETARY_SYSTEMS_SLUG][0]
        assert member.group_slug == SOLAR_SYSTEM_SLUG


class TestHosts:
    """A host is one planetary system, whatever its planets."""

    def test_counts(self, tmp_path, session):
        pages = build_system_pages(
            [],
            Counter({1: 1, 2: 3}),
            ObjectNames(_entities({}), session),
            tmp_path / "none",
        )
        assert pages.member_counts[PLANETARY_SYSTEMS_SLUG] == 3
        stats = pages.extra_stats[PLANETARY_SYSTEMS_SLUG]
        assert stats.multi_planet_system_count == 2


class TestCards:
    """The system of the most stars or planets, among the roots of the tiles."""

    def test_the_most_stars(self):
        tiles = [
            {"depth": [0, 1, 0], "stars": [2, 30, 4], "id": [1, 2, 3]},
            {"depth": [1], "stars": [9], "id": [4]},
            {"depth": [0], "stars": [3], "id": [5]},
        ]

        class Tile:
            def __init__(self, columns):
                self.columns = columns

            def numpy(self, name):
                return np.array(self.columns[name])

        reader = MagicMock()
        reader.leaf.side_effect = lambda _, leaf: Tile(tiles[leaf])
        reader.split.return_value.level = [0, 0, 0]
        assert _root_counts(reader) == (3, 2, (4, 3))
